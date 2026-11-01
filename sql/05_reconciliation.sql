-- Reconciliation (R3): compare what landed in RAW with what the manifest says should
-- have landed, and record the result in AUDIT.load_log. Also checks that every RAW
-- line ends up either staged or quarantined.
--
-- One load_log row per load_id (decisions D6). Running this again adds rows only for
-- loads it has not seen yet, so it is safe to re-run.
USE ROLE SYSADMIN;
USE WAREHOUSE FINANCE_WH;
USE SCHEMA FINANCE_DB.AUDIT;

-- ------------------------------------------------------ 1. RAW vs manifest
-- What each source file holds in RAW right now, per load_id.
CREATE OR REPLACE VIEW v_raw_load_summary AS
SELECT source_file, MAX(load_id) AS load_id, COUNT(DISTINCT load_id) AS load_id_count,
       COUNT(*) AS actual_row_count, NULL::NUMBER(18, 2) AS actual_amount_total,
       MIN(loaded_at) AS started_at, MAX(loaded_at) AS finished_at
FROM FINANCE_DB.RAW.raw_customers GROUP BY source_file
UNION ALL
SELECT source_file, MAX(load_id), COUNT(DISTINCT load_id),
       COUNT(*), NULL::NUMBER(18, 2), MIN(loaded_at), MAX(loaded_at)
FROM FINANCE_DB.RAW.raw_accounts GROUP BY source_file
UNION ALL
SELECT source_file, MAX(load_id), COUNT(DISTINCT load_id),
       COUNT(*), NULL::NUMBER(18, 2), MIN(loaded_at), MAX(loaded_at)
FROM FINANCE_DB.RAW.raw_merchants GROUP BY source_file
UNION ALL
SELECT source_file, MAX(load_id), COUNT(DISTINCT load_id),
       COUNT(*), SUM(TRY_TO_NUMBER(amount, 18, 2)), MIN(loaded_at), MAX(loaded_at)
FROM FINANCE_DB.RAW.raw_transactions GROUP BY source_file;

-- Live check: the same comparison against the manifest, always on the current RAW state.
-- Use this to catch rows that went missing after a load. load_log below is the history.
CREATE OR REPLACE VIEW v_live_reconciliation AS
SELECT r.source_file, r.load_id, m.business_date,
       m.row_count AS expected_row_count, r.actual_row_count,
       m.amount_total AS expected_amount_total, r.actual_amount_total,
       (r.load_id_count = 1
          AND m.row_count = r.actual_row_count
          AND (m.amount_total IS NULL OR m.amount_total = r.actual_amount_total)) AS ok
FROM v_raw_load_summary r
JOIN manifest m ON m.source_file = r.source_file;

-- Record each load once in load_log (D6). Re-running adds rows only for load_ids
-- it has not seen. Because it skips seen load_ids, a later change to RAW shows up in
-- v_live_reconciliation, not here.
INSERT INTO load_log (
    load_id, source_file, business_date, expected_row_count, actual_row_count,
    expected_amount_total, actual_amount_total, status, message, started_at, finished_at
)
SELECT r.load_id, r.source_file, r.business_date, r.expected_row_count, r.actual_row_count,
       r.expected_amount_total, r.actual_amount_total,
       IFF(r.ok, 'PASS', 'FAIL'),
       IFF(r.ok,
           'rows and amount match the manifest',
           'mismatch: ' || s.load_id_count || ' load ids, expected ' || r.expected_row_count
             || ' rows, got ' || r.actual_row_count
             || IFF(r.expected_amount_total IS NULL, '', ', expected amount ' || r.expected_amount_total
                    || ', got ' || COALESCE(r.actual_amount_total::VARCHAR, 'NULL'))),
       s.started_at, s.finished_at
FROM v_live_reconciliation r
JOIN v_raw_load_summary s ON s.source_file = r.source_file
WHERE NOT EXISTS (SELECT 1 FROM load_log g WHERE g.load_id = r.load_id);

-- ------------------------------------------- 2. RAW = STAGING + quarantine
-- Counted by RAW line, so a row is never counted twice (D4).
CREATE OR REPLACE VIEW v_staging_reconciliation AS
WITH raw_counts AS (
    SELECT source_file, COUNT(*) AS raw_rows FROM FINANCE_DB.RAW.raw_transactions GROUP BY source_file
),
staged AS (
    SELECT source_file, COUNT(*) AS staged_rows FROM FINANCE_DB.STAGING.stg_transactions GROUP BY source_file
),
quarantined AS (
    SELECT source_file, COUNT(*) AS quarantined_rows FROM FINANCE_DB.STAGING.quarantine_transactions GROUP BY source_file
)
SELECT r.source_file,
       r.raw_rows,
       COALESCE(s.staged_rows, 0)      AS staged_rows,
       COALESCE(q.quarantined_rows, 0) AS quarantined_rows,
       r.raw_rows = COALESCE(s.staged_rows, 0) + COALESCE(q.quarantined_rows, 0) AS balances
FROM raw_counts r
LEFT JOIN staged s      ON s.source_file = r.source_file
LEFT JOIN quarantined q ON q.source_file = r.source_file;

-- Dimensions: typed copies must have the same row count as RAW.
CREATE OR REPLACE VIEW v_dimension_reconciliation AS
SELECT 'dimensions/customers.csv' AS source_file,
       (SELECT COUNT(*) FROM FINANCE_DB.RAW.raw_customers)     AS raw_rows,
       (SELECT COUNT(*) FROM FINANCE_DB.STAGING.stg_customers) AS staged_rows
UNION ALL
SELECT 'dimensions/accounts.csv',
       (SELECT COUNT(*) FROM FINANCE_DB.RAW.raw_accounts),
       (SELECT COUNT(*) FROM FINANCE_DB.STAGING.stg_accounts)
UNION ALL
SELECT 'dimensions/merchants.csv',
       (SELECT COUNT(*) FROM FINANCE_DB.RAW.raw_merchants),
       (SELECT COUNT(*) FROM FINANCE_DB.STAGING.stg_merchants);

-- ------------------------------------------------ 3. current status per file
-- The latest load_log row per source file is its current status (D6).
CREATE OR REPLACE VIEW v_load_status AS
SELECT *
FROM load_log
QUALIFY ROW_NUMBER() OVER (PARTITION BY source_file ORDER BY started_at DESC) = 1;

-- Checks to read after running this script. Expect: no FAIL, every balances = TRUE,
-- and no row with staged_rows different from raw_rows in v_dimension_reconciliation.
SELECT status, COUNT(*) AS files FROM v_load_status GROUP BY status;
SELECT COUNT(*) AS files_failing_live_check FROM v_live_reconciliation WHERE NOT ok;
SELECT COUNT(*) AS unbalanced_files FROM v_staging_reconciliation WHERE NOT balances;
SELECT * FROM v_dimension_reconciliation WHERE raw_rows <> staged_rows;
