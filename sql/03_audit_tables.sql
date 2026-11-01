-- AUDIT layer: what each file should contain (manifest) and what each load
-- actually produced (load_log).
USE ROLE SYSADMIN;
USE SCHEMA FINANCE_DB.AUDIT;

-- One row per source file, loaded from the manifest.csv files in Blob.
CREATE TABLE IF NOT EXISTS manifest (
    source_file   VARCHAR NOT NULL PRIMARY KEY,
    file_type     VARCHAR NOT NULL,       -- 'transactions' or 'dimension'
    business_date DATE,                   -- NULL for dimension files
    row_count     NUMBER  NOT NULL,
    amount_total  NUMBER(18, 2),          -- NULL for dimension files
    sha256        VARCHAR NOT NULL,
    loaded_at     TIMESTAMP_NTZ NOT NULL
);

-- One row per load attempt. Re-running a day adds a new row, so the history of
-- failures and fixes is kept; the latest row per source_file is its current status.
-- Filled by the reconciliation step (R3, Sprint 2).
CREATE TABLE IF NOT EXISTS load_log (
    load_id               VARCHAR NOT NULL PRIMARY KEY,
    source_file           VARCHAR NOT NULL,
    business_date         DATE,
    expected_row_count    NUMBER,
    actual_row_count      NUMBER,
    expected_amount_total NUMBER(18, 2),
    actual_amount_total   NUMBER(18, 2),
    status                VARCHAR NOT NULL,   -- 'PASS' or 'FAIL'
    message               VARCHAR,
    started_at            TIMESTAMP_NTZ NOT NULL,
    finished_at           TIMESTAMP_NTZ
);

-- Load or refresh every manifest in the container. MERGE keeps it idempotent.
MERGE INTO manifest t
USING (
    SELECT $2 AS source_file, $1 AS file_type, TRY_TO_DATE($3) AS business_date,
           TO_NUMBER($4) AS row_count, TRY_TO_NUMBER($5, 18, 2) AS amount_total, $6 AS sha256
    FROM @FINANCE_DB.RAW.landing_stage
        (FILE_FORMAT => 'FINANCE_DB.RAW.csv_with_header', PATTERN => '.*manifest[.]csv')
) s
ON t.source_file = s.source_file
WHEN MATCHED THEN UPDATE SET
    file_type = s.file_type, business_date = s.business_date, row_count = s.row_count,
    amount_total = s.amount_total, sha256 = s.sha256, loaded_at = SYSDATE()
WHEN NOT MATCHED THEN INSERT
    (source_file, file_type, business_date, row_count, amount_total, sha256, loaded_at)
    VALUES (s.source_file, s.file_type, s.business_date, s.row_count, s.amount_total, s.sha256, SYSDATE());

-- Expect 33 rows: 30 transaction files and 3 dimension files.
SELECT file_type, COUNT(*) AS files, SUM(row_count) AS rows FROM manifest GROUP BY file_type;
