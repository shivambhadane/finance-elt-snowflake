-- Sprint 1: load one day into RAW by hand and check it against its manifest.
-- This is the load that ADF will automate in Sprint 2. It is idempotent: the
-- DELETE and COPY run in one transaction, so re-running replaces the day's rows
-- instead of doubling them.
--
-- To load another day, change the date in the three places marked <-- DATE.
USE ROLE SYSADMIN;
USE WAREHOUSE FINANCE_WH;
USE SCHEMA FINANCE_DB.RAW;

SET source_file = 'transactions/business_date=2026-09-01/transactions_20260901.csv';  -- <-- DATE
SET load_id = UUID_STRING();

BEGIN;

DELETE FROM raw_transactions WHERE source_file = $source_file;

-- FORCE = TRUE: Snowflake skips files it has loaded before; a re-run must not be skipped.
COPY INTO raw_transactions
    (transaction_id, account_id, merchant_id, txn_ts, amount, currency, txn_type, channel,
     source_file, source_row_number)
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER
    FROM @landing_stage/transactions/business_date=2026-09-01/                         -- <-- DATE
)
PATTERN = '.*transactions_20260901[.]csv'                                              -- <-- DATE
FORCE = TRUE;

UPDATE raw_transactions
SET load_id = $load_id, loaded_at = SYSDATE()
WHERE source_file = $source_file AND load_id IS NULL;

COMMIT;

-- Check 1: rows and amount total match the manifest (R3 will write this to AUDIT.load_log).
SELECT m.row_count                                   AS expected_rows,
       COUNT(r.source_row_number)                    AS actual_rows,
       m.amount_total                                AS expected_amount,
       SUM(TRY_TO_NUMBER(r.amount, 18, 2))           AS actual_amount,
       IFF(expected_rows = actual_rows AND expected_amount = actual_amount, 'PASS', 'FAIL') AS status
FROM FINANCE_DB.AUDIT.manifest m
LEFT JOIN raw_transactions r ON r.source_file = m.source_file
WHERE m.source_file = $source_file
GROUP BY m.row_count, m.amount_total;

-- Check 2: audit columns are filled and there is exactly one load_id for the file.
SELECT COUNT(DISTINCT load_id) AS load_ids, COUNT_IF(loaded_at IS NULL) AS missing_loaded_at
FROM raw_transactions WHERE source_file = $source_file;

-- Check 3: does source_row_number count the header line? The generator's ground
-- truth numbers data lines from 1. If this returns 2, subtract 1 when matching.
SELECT MIN(source_row_number), MAX(source_row_number)
FROM raw_transactions WHERE source_file = $source_file;
