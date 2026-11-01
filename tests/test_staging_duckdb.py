"""Run the STAGING, reconciliation and REPORTING SQL on generated data, and compare the
result with the answer key.

Snowflake is not available in CI, so this runs the same SQL files in DuckDB. sqlglot
translates the Snowflake dialect, and a few known translation gaps are patched below
(array indexing, INSERT OVERWRITE, the ARRAY column type). That makes this a check of
the logic, not of Snowflake itself. The first run in a real Snowflake account is still
the authority; if the two disagree, fix the SQL or the translation, not the answer key.
"""

import csv
import re
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
sqlglot = pytest.importorskip("sqlglot")

from generator.generate import Config, generate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SMALL = Config(days=3, min_rows_per_day=3_000, max_rows_per_day=3_000,
               customers=300, accounts=500, merchants=50)


def statements(path: Path) -> list[str]:
    """Split a Snowflake script into statements. Drops comments, USE, SET and transactions."""
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))
    out = []
    for s in text.split(";"):
        s = s.strip()
        if s and not s.upper().startswith(("USE ", "SET ", "BEGIN", "COMMIT", "SELECT ")):
            out.append(s)
    return out


def to_duckdb(sql: str) -> str:
    s = sqlglot.transpile(sql, read="snowflake", write="duckdb")[0]
    s = re.sub(r"CAST\((\w+) -> '\$\[0\]' AS TEXT\)", r"\1[1]", s)  # Snowflake GET(arr, 0) -> DuckDB 1-based
    s = re.sub(r"dq_rules \[\]", "dq_rules VARCHAR[]", s)           # ARRAY column type
    s = re.sub(r"INSERT OVERWRITE TABLE (\w+)", r"DELETE FROM \1; INSERT INTO \1", s)
    return s


def run_script(con, rel_path: str, schema: str) -> None:
    con.execute(f"USE FINANCE_DB.{schema}")
    for s in statements(ROOT / rel_path):
        if s.upper().startswith("MERGE"):
            continue  # reads from the Azure stage; the test loads manifests directly instead
        con.execute(to_duckdb(s))


def load_raw(con, landing: Path) -> None:
    con.execute("USE FINANCE_DB.AUDIT")
    for m in sorted(landing.rglob("manifest.csv")):
        with m.open(newline="") as f:
            for r in csv.DictReader(f):
                con.execute("INSERT INTO manifest VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                            [r["source_file"], r["file_type"], r["business_date"] or None,
                             int(r["row_count"]), r["amount_total"] or None, r["sha256"]])

    con.execute("USE FINANCE_DB.RAW")
    for path in sorted(landing.rglob("*.csv")):
        if path.name == "manifest.csv":
            continue
        rel = path.relative_to(landing).as_posix()
        if rel.startswith("transactions/"):
            table = "raw_transactions"
        else:
            table = {"customers": "raw_customers", "accounts": "raw_accounts",
                     "merchants": "raw_merchants"}[path.stem]
        with path.open(newline="") as f:
            rows = list(csv.reader(f))[1:]
        load_id = f"LOAD-{rel}"
        params = []
        for n, row in enumerate(rows, start=1):
            vals = [v if v != "" else None for v in row]
            params.append(vals + [rel, n, "2026-09-01 00:00:00", load_id])
        marks = ",".join("?" * len(params[0]))
        con.executemany(f"INSERT INTO {table} VALUES ({marks})", params)


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    data = tmp_path_factory.mktemp("sim")
    generate(SMALL, data)

    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS FINANCE_DB")
    for schema in ("RAW", "STAGING", "AUDIT", "REPORTING"):
        con.execute(f"CREATE SCHEMA FINANCE_DB.{schema}")
    run_script(con, "sql/02_raw_tables.sql", "RAW")
    run_script(con, "sql/03_audit_tables.sql", "AUDIT")  # the MERGE from the stage is replaced below
    load_raw(con, data / "landing")
    run_script(con, "sql/04_staging.sql", "STAGING")
    run_script(con, "sql/05_reconciliation.sql", "AUDIT")
    run_script(con, "sql/06_reporting.sql", "REPORTING")
    yield con, data
    con.close()


def test_quarantine_matches_answer_key_exactly(warehouse):
    con, data = warehouse
    got = set(con.execute(
        "SELECT source_file, source_row_number, dq_rule FROM FINANCE_DB.STAGING.quarantine_transactions").fetchall())
    truth = {(r["source_file"], int(r["line_number"]), r["dq_rule"])
             for r in csv.DictReader((data / "ground_truth" / "dirty_rows.csv").open(newline=""))}
    assert truth, "sample should contain dirty rows"
    assert got == truth


def test_every_raw_line_is_staged_or_quarantined(warehouse):
    con, _ = warehouse
    unbalanced = con.execute(
        "SELECT COUNT(*) FROM FINANCE_DB.AUDIT.v_staging_reconciliation WHERE NOT balances").fetchone()[0]
    assert unbalanced == 0


def test_load_log_records_every_file_as_pass(warehouse):
    con, _ = warehouse
    statuses = dict(con.execute("SELECT status, COUNT(*) FROM FINANCE_DB.AUDIT.load_log GROUP BY status").fetchall())
    assert statuses == {"PASS": 6}  # 3 dimension files + 3 transaction files


def test_reconciliation_is_idempotent(warehouse):
    con, _ = warehouse
    before = con.execute("SELECT COUNT(*) FROM FINANCE_DB.AUDIT.load_log").fetchone()[0]
    run_script(con, "sql/05_reconciliation.sql", "AUDIT")
    assert con.execute("SELECT COUNT(*) FROM FINANCE_DB.AUDIT.load_log").fetchone()[0] == before


def test_live_check_catches_a_row_removed_after_load(tmp_path):
    data = tmp_path / "sim"
    generate(SMALL, data)
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS FINANCE_DB")
    for schema in ("RAW", "STAGING", "AUDIT", "REPORTING"):
        con.execute(f"CREATE SCHEMA FINANCE_DB.{schema}")
    run_script(con, "sql/02_raw_tables.sql", "RAW")
    run_script(con, "sql/03_audit_tables.sql", "AUDIT")
    load_raw(con, data / "landing")
    run_script(con, "sql/04_staging.sql", "STAGING")
    run_script(con, "sql/05_reconciliation.sql", "AUDIT")
    assert con.execute("SELECT COUNT(*) FROM FINANCE_DB.AUDIT.v_live_reconciliation WHERE NOT ok").fetchone()[0] == 0

    con.execute("USE FINANCE_DB.RAW")
    source_file, line = con.execute("SELECT source_file, source_row_number FROM raw_transactions LIMIT 1").fetchone()
    con.execute("DELETE FROM raw_transactions WHERE source_file = ? AND source_row_number = ?", [source_file, line])
    assert con.execute("SELECT COUNT(*) FROM FINANCE_DB.AUDIT.v_live_reconciliation WHERE NOT ok").fetchone()[0] == 1


def test_reporting_summary_adds_up_to_fact(warehouse):
    con, _ = warehouse
    fact_rows, fact_net = con.execute(
        "SELECT COUNT(*), SUM(amount) FROM FINANCE_DB.REPORTING.fct_transactions").fetchone()
    summary_rows, summary_net = con.execute(
        "SELECT SUM(txn_count), SUM(net_amount) FROM FINANCE_DB.REPORTING.rpt_daily_summary").fetchone()
    assert fact_rows == summary_rows
    assert fact_net == summary_net
