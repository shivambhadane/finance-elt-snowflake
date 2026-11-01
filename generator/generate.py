"""Generate synthetic daily transaction batches, dimension files and manifests.

Output layout (``<out>/landing`` mirrors the Blob container one-to-one):

    <out>/landing/dimensions/{customers,accounts,merchants}.csv + manifest.csv
    <out>/landing/transactions/business_date=YYYY-MM-DD/transactions_YYYYMMDD.csv + manifest.csv
    <out>/ground_truth/dirty_rows.csv   answer key for the DQ checks, never uploaded

Every random choice comes from a ``random.Random`` seeded from ``--seed`` plus the
file's name, so the same seed always produces byte-identical files and one day
can be regenerated on its own.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

TRANSACTION_COLUMNS = [
    "transaction_id", "account_id", "merchant_id", "txn_ts",
    "amount", "currency", "txn_type", "channel",
]
MANIFEST_COLUMNS = ["file_type", "source_file", "business_date", "row_count", "amount_total", "sha256"]
GROUND_TRUTH_COLUMNS = ["source_file", "line_number", "transaction_id", "dq_rule"]

# The six injected issue types; names match the dq_rule values STAGING will write.
DQ_RULES = [
    "duplicate_transaction_id",
    "missing_account_id",
    "orphan_account_id",
    "invalid_amount",
    "invalid_currency",
    "ts_outside_business_date",
]

CITIES = [
    ("Mumbai", "MH"), ("Pune", "MH"), ("Delhi", "DL"), ("Bengaluru", "KA"),
    ("Chennai", "TN"), ("Hyderabad", "TS"), ("Kolkata", "WB"), ("Ahmedabad", "GJ"),
    ("Jaipur", "RJ"), ("Lucknow", "UP"), ("Kochi", "KL"), ("Nagpur", "MH"),
]
FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Arjun", "Sai", "Rohan", "Ishaan", "Kabir", "Ananya", "Diya",
    "Priya", "Sneha", "Kavya", "Meera", "Riya", "Neha", "Rahul", "Vikram", "Pooja", "Asha",
]
LAST_NAMES = [
    "Sharma", "Patel", "Iyer", "Reddy", "Nair", "Gupta", "Kulkarni", "Deshmukh", "Singh", "Rao",
    "Joshi", "Menon", "Bhat", "Chopra", "Das", "Mehta", "Pillai", "Verma", "Shah", "Khan",
]
# category -> (lognormal mu, sigma) for purchase amounts in INR
CATEGORIES = {
    "GROCERY": (6.5, 0.8), "FUEL": (7.3, 0.5), "DINING": (6.8, 0.7),
    "ELECTRONICS": (9.5, 1.0), "TRAVEL": (8.8, 0.9), "UTILITIES": (7.5, 0.6),
    "HEALTHCARE": (7.2, 0.9), "APPAREL": (7.6, 0.8), "ENTERTAINMENT": (6.6, 0.7),
    "EDUCATION": (9.0, 0.8),
}
CHANNELS = (["UPI", "POS", "ONLINE", "NETBANKING"], [45, 25, 20, 10])
TXN_TYPES = (["PURCHASE", "BILL_PAYMENT", "REFUND"], [93, 4, 3])
WRONG_CURRENCIES = ["USD", "EUR", "GBP", "AED"]


@dataclass
class Config:
    seed: int = 42
    start_date: date = date(2026, 9, 1)
    days: int = 30
    min_rows_per_day: int = 34_000
    max_rows_per_day: int = 36_000
    dirty_rate: float = 0.01
    customers: int = 20_000
    accounts: int = 30_000
    merchants: int = 2_000


def rng_for(cfg: Config, name: str) -> random.Random:
    return random.Random(f"{cfg.seed}:{name}")


def fmt_amount(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    return f"{sign}{paise // 100}.{paise % 100:02d}"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def account_id(n: int) -> str:
    return f"ACC{n:07d}"


def generate_dimensions(cfg: Config, landing: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Write the three dimension files; return active account ids and (merchant_id, category)."""
    rng = rng_for(cfg, "dimensions")
    dim_dir = landing / "dimensions"

    customers = []
    for i in range(1, cfg.customers + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        city, state = rng.choice(CITIES)
        created = date(2015, 1, 1) + timedelta(days=rng.randrange(3650))
        segment = rng.choices(["RETAIL", "PREMIUM", "BUSINESS"], [80, 15, 5])[0]
        customers.append([f"CUS{i:06d}", f"{first} {last}", f"{first}.{last}{i}@example.com".lower(),
                          city, state, segment, created.isoformat()])

    accounts, active = [], []
    for i in range(1, cfg.accounts + 1):
        # The first `customers` accounts cover every customer once; the rest are second accounts.
        cust = i if i <= cfg.customers else rng.randint(1, cfg.customers)
        status = rng.choices(["ACTIVE", "DORMANT"], [95, 5])[0]
        opened = date(2015, 1, 1) + timedelta(days=rng.randrange(4000))
        accounts.append([account_id(i), f"CUS{cust:06d}",
                         rng.choices(["SAVINGS", "CURRENT", "CREDIT_CARD"], [60, 15, 25])[0],
                         f"BR{rng.randint(1, 250):04d}", opened.isoformat(), status])
        if status == "ACTIVE":
            active.append(account_id(i))

    merchants, merchant_refs = [], []
    categories = list(CATEGORIES)
    for i in range(1, cfg.merchants + 1):
        category = rng.choice(categories)
        city, _ = rng.choice(CITIES)
        mid = f"MER{i:05d}"
        merchants.append([mid, f"{rng.choice(LAST_NAMES)} {category.title()} {i}", category, city])
        merchant_refs.append((mid, category))

    write_csv(dim_dir / "customers.csv",
              ["customer_id", "full_name", "email", "city", "state", "segment", "created_date"], customers)
    write_csv(dim_dir / "accounts.csv",
              ["account_id", "customer_id", "account_type", "branch_code", "opened_date", "status"], accounts)
    write_csv(dim_dir / "merchants.csv", ["merchant_id", "merchant_name", "category", "city"], merchants)

    manifest = []
    for name, rows in [("customers", customers), ("accounts", accounts), ("merchants", merchants)]:
        path = dim_dir / f"{name}.csv"
        manifest.append(["dimension", f"dimensions/{name}.csv", "", str(len(rows)), "", sha256_of(path)])
    write_csv(dim_dir / "manifest.csv", MANIFEST_COLUMNS, manifest)
    return active, merchant_refs


def clean_transaction(rng: random.Random, txn_id: str, ts: datetime,
                      accounts: list[str], merchants: list[tuple[str, str]]) -> list:
    merchant_id, category = rng.choice(merchants)
    mu, sigma = CATEGORIES[category]
    paise = int(round(min(max(rng.lognormvariate(mu, sigma), 10.0), 200_000.0) * 100))
    txn_type = rng.choices(*TXN_TYPES)[0]
    if txn_type == "REFUND":
        paise = -paise  # see docs/decisions.md: refunds carry negative amounts
    return [txn_id, rng.choice(accounts), merchant_id, ts.strftime("%Y-%m-%d %H:%M:%S"),
            paise, "INR", txn_type, rng.choices(*CHANNELS)[0]]


def corrupt(rng: random.Random, row: list, rule: str, business_date: date) -> None:
    """Make `row` break exactly `rule` and no other rule."""
    if rule == "missing_account_id":
        row[1] = ""
    elif rule == "orphan_account_id":
        row[1] = f"ACC9{rng.randrange(1_000_000):06d}"  # real ids stay far below ACC9000000
    elif rule == "invalid_amount":
        if row[6] == "REFUND":
            row[6] = "PURCHASE"
        row[4] = 0 if rng.random() < 0.3 else -abs(row[4])
    elif rule == "invalid_currency":
        row[5] = rng.choice(WRONG_CURRENCIES)
    elif rule == "ts_outside_business_date":
        other_day = business_date + timedelta(days=rng.choice([-1, 1]))
        ts = datetime.combine(other_day, datetime.min.time()) + timedelta(seconds=rng.randrange(86_400))
        row[3] = ts.strftime("%Y-%m-%d %H:%M:%S")
    else:
        raise ValueError(rule)


def generate_day(cfg: Config, landing: Path, business_date: date,
                 accounts: list[str], merchants: list[tuple[str, str]]) -> list[list[str]]:
    """Write one day's transaction file and manifest; return its ground-truth rows."""
    tag = business_date.strftime("%Y%m%d")
    rng = rng_for(cfg, f"transactions_{tag}")
    total_rows = rng.randint(cfg.min_rows_per_day, cfg.max_rows_per_day)

    # Split the dirty rows as evenly as possible across the six rules.
    n_dirty = round(total_rows * cfg.dirty_rate)
    per_rule = {rule: n_dirty // len(DQ_RULES) for rule in DQ_RULES}
    for rule in DQ_RULES[: n_dirty % len(DQ_RULES)]:
        per_rule[rule] += 1

    # Duplicates are extra lines, so generate fewer base rows to hit total_rows exactly.
    n_base = total_rows - per_rule["duplicate_transaction_id"]
    midnight = datetime.combine(business_date, datetime.min.time())
    seconds = sorted(rng.randrange(86_400) for _ in range(n_base))
    base = [clean_transaction(rng, f"TXN{tag}{i + 1:07d}", midnight + timedelta(seconds=s), accounts, merchants)
            for i, s in enumerate(seconds)]

    picked = iter(rng.sample(range(n_base), n_dirty))
    rule_of: dict[int, str] = {}  # id(row) -> rule, for rows that are dirty
    copies_after: dict[int, list[list]] = {}
    for rule in DQ_RULES:
        for _ in range(per_rule[rule]):
            idx = next(picked)
            if rule == "duplicate_transaction_id":
                # The original stays clean; the later copy is the one STAGING must reject.
                copy = list(base[idx])
                copies_after.setdefault(rng.randrange(idx, n_base), []).append(copy)
                rule_of[id(copy)] = rule
            else:
                corrupt(rng, base[idx], rule, business_date)
                rule_of[id(base[idx])] = rule

    rows = []
    for i, row in enumerate(base):
        rows.append(row)
        rows.extend(copies_after.get(i, []))

    source_file = f"transactions/business_date={business_date.isoformat()}/transactions_{tag}.csv"
    ground_truth = [[source_file, str(line), row[0], rule_of[id(row)]]
                    for line, row in enumerate(rows, start=1) if id(row) in rule_of]

    amount_total = sum(row[4] for row in rows)
    for row in rows:
        row[4] = fmt_amount(row[4])
    path = landing / source_file
    write_csv(path, TRANSACTION_COLUMNS, rows)
    write_csv(path.parent / "manifest.csv", MANIFEST_COLUMNS,
              [["transactions", source_file, business_date.isoformat(), str(len(rows)),
                fmt_amount(amount_total), sha256_of(path)]])
    return ground_truth


def generate(cfg: Config, out: Path) -> None:
    landing = out / "landing"
    accounts, merchants = generate_dimensions(cfg, landing)
    ground_truth = []
    for d in range(cfg.days):
        ground_truth += generate_day(cfg, landing, cfg.start_date + timedelta(days=d), accounts, merchants)
    write_csv(out / "ground_truth" / "dirty_rows.csv", GROUND_TRUTH_COLUMNS, ground_truth)


def parse_args(argv: list[str] | None = None) -> tuple[Config, Path]:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("data"))
    p.add_argument("--seed", type=int, default=Config.seed)
    p.add_argument("--start-date", type=date.fromisoformat, default=Config.start_date)
    p.add_argument("--days", type=int, default=Config.days)
    p.add_argument("--min-rows-per-day", type=int, default=Config.min_rows_per_day)
    p.add_argument("--max-rows-per-day", type=int, default=Config.max_rows_per_day)
    p.add_argument("--dirty-rate", type=float, default=Config.dirty_rate)
    p.add_argument("--customers", type=int, default=Config.customers)
    p.add_argument("--accounts", type=int, default=Config.accounts)
    p.add_argument("--merchants", type=int, default=Config.merchants)
    a = p.parse_args(argv)
    return Config(a.seed, a.start_date, a.days, a.min_rows_per_day, a.max_rows_per_day,
                  a.dirty_rate, a.customers, a.accounts, a.merchants), a.out


def main(argv: list[str] | None = None) -> None:
    cfg, out = parse_args(argv)
    generate(cfg, out)
    print(f"Wrote {cfg.days} transaction files and 3 dimension files to {out / 'landing'}")


if __name__ == "__main__":
    main()
