"""Static checks on the Snowflake SQL. No Snowflake account is needed.

These catch syntax errors (sqlglot's Snowflake dialect) and drift between the SQL and
the generator: the rule names in STAGING must be exactly the generator's DQ_RULES.
They do not prove the SQL returns the right answer; the first load in Snowflake does that.
"""

import re
from pathlib import Path

import pytest
import sqlglot

from generator.generate import DQ_RULES

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = sorted((ROOT / "sql").rglob("*.sql"))


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_sql_file_parses_as_snowflake(path):
    sqlglot.parse(path.read_text(encoding="utf-8"), read="snowflake")


def test_staging_rule_names_match_generator():
    # The rule names written as string literals in 04_staging.sql must be exactly the
    # generator's DQ_RULES. Each rule appears once in the classification, so none is skipped (D4).
    staging = (ROOT / "sql" / "04_staging.sql").read_text(encoding="utf-8")
    literals = set(re.findall(r"'([a-z_]+)'", staging))
    assert set(DQ_RULES) <= literals
    for rule in DQ_RULES:
        assert staging.count(f"'{rule}'") == 1, rule


def test_reporting_only_reads_staging():
    reporting = (ROOT / "sql" / "06_reporting.sql").read_text(encoding="utf-8")
    assert "FINANCE_DB.RAW." not in reporting
    assert "FINANCE_DB.AUDIT." not in reporting
