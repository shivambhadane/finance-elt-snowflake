# Finance Transactions ELT Pipeline (Snowflake)

A governed ELT pipeline that loads 30 daily batches of synthetic finance transactions (1M+ rows, ~1% deliberately dirty) into Snowflake. It proves every load is complete and correct through reconciliation, audit columns and data quality checks.

```
generator ──> Azure Blob ──ADF──> RAW ──> STAGING ──> REPORTING
 (Python)     (1 folder/day)      │        │  └─> quarantine
                                  │        └─ data quality rules (PySpark)
                                  └─ reconciliation vs manifest ──> AUDIT.load_log
```

**Status:** Sprint 1 of 6. The generator, Blob upload, RAW/AUDIT tables and a by-hand first load are in place. ADF, STAGING and REPORTING come next.

## Repo layout

| Path | What it is |
|------|------------|
| `generator/generate.py` | Writes the 30 transaction files, 3 dimension files, manifests and the ground-truth answer key |
| `generator/validate.py` | Checks files against their manifests; a plain-Python version of the 6 DQ rules must flag exactly the ground-truth rows |
| `scripts/upload_to_blob.py` | Uploads `data/landing/` to Blob, keeping the folder layout |
| `sql/00_setup.sql` … `03_audit_tables.sql` | Warehouse, database, schemas, stage, RAW and AUDIT tables (run in order) |
| `sql/manual/load_first_day.sql` | Idempotent by-hand load of one day into RAW, plus checks against the manifest |
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

Run step 5 twice: the row count must stay the same.

## 4. Test ADF → Snowflake (Sprint 1 blocking question)

1. Create a Data Factory. Add linked services for the storage account and for Snowflake (account identifier, user, password, database `FINANCE_DB`, warehouse `FINANCE_WH`).
2. Make a Copy activity: source is `transactions_20260901.csv`, sink is `RAW.raw_transactions`. Turn on staged copy through the same storage account.
3. If it works, Sprint 2 builds on the Copy activity. If not, ADF runs the COPY INTO from `load_first_day.sql` through a Script activity, and Snowflake does the load. Record what happened in `docs/troubleshooting_log.md`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

GitHub Actions runs the tests and generates and validates a 2-day sample on every push.
