# Finance Transactions ELT Pipeline (Snowflake)

A governed ELT pipeline that loads 30 daily batches of synthetic finance transactions (1M+ rows, ~1% deliberately dirty) into Snowflake. It proves every load is complete and correct through reconciliation, audit columns and data quality checks.

```
generator ──> Azure Blob ──ADF──> RAW ──> STAGING ──> REPORTING
 (Python)     (1 folder/day)      │        │  └─> quarantine
                                  │        └─ data quality rules (PySpark)
                                  └─ reconciliation vs manifest ──> AUDIT.load_log
```

**Status:** Sprint 1 done; STAGING, reconciliation and REPORTING are written and tested against the generator's answer key (in DuckDB, not yet in Snowflake). Still open: ADF automation, the PySpark DQ job, and the first real Snowflake run of the new SQL. See "What is not done" below.

## Repo layout

| Path | What it is |
|------|------------|
| `generator/generate.py` | Writes the 30 transaction files, 3 dimension files, manifests and the ground-truth answer key |
| `generator/validate.py` | Checks files against their manifests; a plain-Python version of the 6 DQ rules must flag exactly the ground-truth rows |
| `scripts/upload_to_blob.py` | Uploads `data/landing/` to Blob, keeping the folder layout |
| `sql/00_setup.sql` … `03_audit_tables.sql` | Warehouse, database, schemas, stage, RAW and AUDIT tables (run in order) |
| `sql/04_staging.sql` | Typed dimensions; transactions classified against the six DQ rules; passed rows to `STAGING.stg_transactions`, failed rows to `STAGING.quarantine_transactions` |
| `sql/05_reconciliation.sql` | RAW vs manifest (one `AUDIT.load_log` row per load), RAW = staged + quarantined, and a live check on the current RAW state |
| `sql/06_reporting.sql` | `REPORTING` dimensions, `fct_transactions` and `rpt_daily_summary`, built from STAGING only |
| `sql/manual/load_first_day.sql` | Idempotent by-hand load of one day into RAW, plus checks against the manifest |
| `sql/manual/load_dimensions.sql` | Idempotent by-hand load of the three dimension files into RAW |
| `docs/decisions.md` | Design decisions (refund sign, timezone, duplicates, manifests, …) |
| `docs/troubleshooting_log.md` | Log of load failures and fixes |

## 1. Generate the data

Needs Python 3.10+. The generator uses only the standard library.

```bash
python -m generator --out data          # ~11 s, ~90 MB, seed 42
python -m generator.validate --out data
```

The same `--seed` always produces byte-identical files. Output:

```
data/landing/                         <- mirrors the Blob container
  dimensions/customers.csv accounts.csv merchants.csv manifest.csv
  transactions/business_date=2026-09-01/transactions_20260901.csv manifest.csv
  ...                                   (30 folders)
data/ground_truth/dirty_rows.csv      <- answer key: source_file, line_number, transaction_id, dq_rule
```

With the default seed: **1,050,687 rows, 10,506 dirty (1.00%)**, about 1,750 of each issue type: duplicate id, missing account, orphan account, invalid amount, non-INR currency, timestamp outside the business date.

## 2. Upload to Azure Blob Storage

Create a storage account in your Azure for Students subscription, then:

```bash
pip install -r requirements.txt
export AZURE_STORAGE_CONNECTION_STRING="<Storage account > Access keys > Connection string>"
python scripts/upload_to_blob.py --container landing
```

## 3. Set up Snowflake and load the first day

In a Snowsight worksheet, run the files in order:

1. `sql/00_setup.sql`: warehouse, database, four schemas
2. `sql/01_stage.sql`: fill in the storage account, container and a SAS token (Read + List)
3. `sql/02_raw_tables.sql`
4. `sql/03_audit_tables.sql`: also loads all manifests into `AUDIT.manifest`
5. `sql/manual/load_first_day.sql`: loads 2026-09-01 and should show `PASS`
6. `sql/manual/load_dimensions.sql`: loads the three dimension files into RAW

Run step 5 twice: the row count must stay the same.

### Build STAGING, reconciliation and REPORTING

Run these in order in a Snowsight worksheet, after the loads. Each one rebuilds from RAW and AUDIT, so re-running is safe:

1. `sql/04_staging.sql`: DQ rules, staged and quarantined rows. The quarantine ends with a count by rule.
2. `sql/05_reconciliation.sql`: writes `AUDIT.load_log`. Expect every row `PASS` and every `balances = TRUE`.
3. `sql/06_reporting.sql`: facts and dimensions. Its last query checks that the summary adds up to the fact table.

Step 2 records each new load in `AUDIT.load_log`, so run it after every load.

## 4. Test ADF → Snowflake (Sprint 1 blocking question)

1. Create a Data Factory. Add linked services for the storage account and for Snowflake (account identifier, user, password, database `FINANCE_DB`, warehouse `FINANCE_WH`).
2. Make a Copy activity: source is `transactions_20260901.csv`, sink is `RAW.raw_transactions`. Turn on staged copy through the same storage account.
3. If it works, Sprint 2 builds on the Copy activity. If not, ADF runs the COPY INTO from `load_first_day.sql` through a Script activity, and Snowflake does the load. Record what happened in `docs/troubleshooting_log.md`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests cover the generator, the validator, and the SQL:

- `tests/test_sql.py` parses every SQL file with sqlglot's Snowflake dialect and checks that the STAGING rule names match the generator's `DQ_RULES`.
- `tests/test_staging_duckdb.py` runs the STAGING, reconciliation and REPORTING SQL in DuckDB on generated data and checks that the quarantine matches the answer key row for row. It also checks that reconciliation is idempotent and that the live check catches a row removed after load. DuckDB is not Snowflake: a few functions are translated by sqlglot, so the first run in a real Snowflake account is still the final check.

GitHub Actions runs the tests and generates and validates a 2-day sample on every push.

## What is not done

- **ADF** (Sprint 2): the by-hand loads in `sql/manual/` are not automated yet.
- **PySpark DQ job**: the open decision in `docs/decisions.md`. Until it is made, the six rules run as SQL in STAGING (D8).
- **Snowflake run**: the SQL in `sql/04`–`06` has not been run in Snowflake yet. It is tested in DuckDB and parsed with the Snowflake dialect.
- **Ground truth in AUDIT**: the answer key stays local (D7). Loading it into AUDIT for the success metric needs a PUT from SnowSQL.
- **Open question**: whether `METADATA$FILE_ROW_NUMBER` counts the header line. Check 3 in `load_first_day.sql` answers it on the first real load.
