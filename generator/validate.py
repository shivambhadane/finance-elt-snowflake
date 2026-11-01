"""Check generated files against their manifests and the ground-truth answer key.

Runs a plain-Python version of the six STAGING data quality rules over every
transaction file and confirms it flags exactly the rows listed in
ground_truth/dirty_rows.csv. Later, the PySpark DQ job's quarantine output should
match this same answer key.

    python -m generator.validate --out data
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from generator.generate import sha256_of


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def failed_rules(row: dict[str, str], business_date: str, seen_ids: set[str], accounts: set[str]) -> list[str]:
    """Return every rule the row breaks. `seen_ids` holds ids from earlier lines in the file."""
    failed = []
    if row["transaction_id"] in seen_ids:
        failed.append("duplicate_transaction_id")
    if not row["account_id"]:
        failed.append("missing_account_id")
    elif row["account_id"] not in accounts:
        failed.append("orphan_account_id")
    amount = Decimal(row["amount"])
    if (row["txn_type"] == "REFUND" and amount >= 0) or (row["txn_type"] != "REFUND" and amount <= 0):
        failed.append("invalid_amount")
    if row["currency"] != "INR":
        failed.append("invalid_currency")
    if datetime.strptime(row["txn_ts"], "%Y-%m-%d %H:%M:%S").date().isoformat() != business_date:
        failed.append("ts_outside_business_date")
    return failed


def validate(out: Path) -> list[str]:
    """Return a list of problems; an empty list means the data set is consistent."""
    landing = out / "landing"
    problems = []

    manifests = [m for path in sorted(landing.rglob("manifest.csv")) for m in read_csv(path)]
    for m in manifests:
        path = landing / m["source_file"]
        rows = read_csv(path)
        if int(m["row_count"]) != len(rows):
            problems.append(f"{m['source_file']}: manifest says {m['row_count']} rows, file has {len(rows)}")
        if m["amount_total"] and Decimal(m["amount_total"]) != sum(Decimal(r["amount"]) for r in rows):
            problems.append(f"{m['source_file']}: amount_total does not match the file")
        if m["sha256"] != sha256_of(path):
            problems.append(f"{m['source_file']}: sha256 does not match the file")

    accounts = {r["account_id"] for r in read_csv(landing / "dimensions" / "accounts.csv")}
    expected = {(g["source_file"], int(g["line_number"])): g["dq_rule"]
                for g in read_csv(out / "ground_truth" / "dirty_rows.csv")}

    flagged = {}
    for m in (m for m in manifests if m["file_type"] == "transactions"):
        seen: set[str] = set()
        for line, row in enumerate(read_csv(landing / m["source_file"]), start=1):
            rules = failed_rules(row, m["business_date"], seen, accounts)
            seen.add(row["transaction_id"])
            if len(rules) > 1:
                problems.append(f"{m['source_file']} line {line}: breaks more than one rule {rules}")
            if rules:
                flagged[(m["source_file"], line)] = rules[0]

    for key in expected.keys() - flagged.keys():
        problems.append(f"{key[0]} line {key[1]}: in ground truth ({expected[key]}) but passes every rule")
    for key in flagged.keys() - expected.keys():
        problems.append(f"{key[0]} line {key[1]}: fails {flagged[key]} but is missing from ground truth")
    for key in expected.keys() & flagged.keys():
        if expected[key] != flagged[key]:
            problems.append(f"{key[0]} line {key[1]}: ground truth says {expected[key]}, rule says {flagged[key]}")
    return problems


def summary(out: Path) -> str:
    landing = out / "landing"
    txn = [m for path in sorted((landing / "transactions").rglob("manifest.csv")) for m in read_csv(path)]
    total_rows = sum(int(m["row_count"]) for m in txn)
    total_amount = sum(Decimal(m["amount_total"]) for m in txn)
    by_rule = Counter(g["dq_rule"] for g in read_csv(out / "ground_truth" / "dirty_rows.csv"))
    dirty = sum(by_rule.values())
    lines = [f"{len(txn)} transaction files, {total_rows:,} rows, amount total {total_amount:,} INR",
             f"{dirty:,} dirty rows ({dirty / total_rows:.2%}):"]
    lines += [f"  {rule:<26} {n:>6,}" for rule, n in sorted(by_rule.items())]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("data"))
    out = p.parse_args(argv).out
    problems = validate(out)
    print(summary(out))
    if problems:
        print(f"\n{len(problems)} problem(s):", *problems[:50], sep="\n  ")
        sys.exit(1)
    print("\nOK: manifests match the files and the DQ rules flag exactly the ground-truth rows")


if __name__ == "__main__":
    main()
