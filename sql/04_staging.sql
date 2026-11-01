-- STAGING layer: typed dimensions, and transactions that passed the six data
-- quality rules, plus the quarantine for rows that failed one or more.
--
-- The rules are the ones in generator/generate.py (DQ_RULES) and generator/validate.py.
-- Every rule is checked on every row (decisions D4). If a row breaks several rules,
-- dq_rule holds the first one in the order below and dq_rules holds all of them.
-- A duplicate is the later copy of a transaction_id in the same file (D3).
--
-- Everything here is rebuilt from RAW and AUDIT on each run (INSERT OVERWRITE), so
-- re-running is safe. Run after the loads in sql/manual/ and before 05 and 06.
USE ROLE SYSADMIN;
USE WAREHOUSE FINANCE_WH;
USE SCHEMA FINANCE_DB.STAGING;

-- ---------------------------------------------------------------- tables
CREATE TABLE IF NOT EXISTS stg_customers (
    customer_id       VARCHAR NOT NULL,
    full_name         VARCHAR,
    email             VARCHAR,
    city              VARCHAR,
    state             VARCHAR,
    segment           VARCHAR,
    created_date      DATE,
    source_row_number NUMBER  NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_accounts (
    account_id        VARCHAR NOT NULL,
    customer_id       VARCHAR,
    account_type      VARCHAR,
    branch_code       VARCHAR,
    opened_date       DATE,
    status            VARCHAR,
    source_row_number NUMBER  NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_merchants (
    merchant_id       VARCHAR NOT NULL,
    merchant_name     VARCHAR,
    category          VARCHAR,
    city              VARCHAR,
    source_row_number NUMBER  NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_transactions (
    transaction_id    VARCHAR       NOT NULL,
    account_id        VARCHAR       NOT NULL,
    merchant_id       VARCHAR,
    txn_ts            TIMESTAMP_NTZ NOT NULL,
    amount            NUMBER(18, 2) NOT NULL,   -- refunds are negative (D1)
    currency          VARCHAR       NOT NULL,
    txn_type          VARCHAR       NOT NULL,
    channel           VARCHAR,
    business_date     DATE          NOT NULL,
    source_file       VARCHAR       NOT NULL,
    source_row_number NUMBER        NOT NULL,
    load_id           VARCHAR,
    loaded_at         TIMESTAMP_NTZ
);

-- Quarantined rows keep the raw text of every column, so they can be inspected as received.
CREATE TABLE IF NOT EXISTS quarantine_transactions (
    transaction_id    VARCHAR,
    account_id        VARCHAR,
    merchant_id       VARCHAR,
    txn_ts            VARCHAR,
    amount            VARCHAR,
    currency          VARCHAR,
    txn_type          VARCHAR,
    channel           VARCHAR,
    business_date     DATE,
    source_file       VARCHAR NOT NULL,
    source_row_number NUMBER  NOT NULL,
    dq_rule           VARCHAR NOT NULL,   -- first failed rule, in the order below
    dq_rules          ARRAY   NOT NULL,   -- every failed rule
    load_id           VARCHAR,
    quarantined_at    TIMESTAMP_NTZ NOT NULL
);

-- ------------------------------------------------------- dimensions (typed)
INSERT OVERWRITE INTO stg_customers
SELECT customer_id, full_name, email, city, state, segment,
       TRY_TO_DATE(created_date), source_row_number
FROM FINANCE_DB.RAW.raw_customers;

INSERT OVERWRITE INTO stg_accounts
SELECT account_id, customer_id, account_type, branch_code,
       TRY_TO_DATE(opened_date), status, source_row_number
FROM FINANCE_DB.RAW.raw_accounts;

INSERT OVERWRITE INTO stg_merchants
SELECT merchant_id, merchant_name, category, city, source_row_number
FROM FINANCE_DB.RAW.raw_merchants;

-- ------------------------------------------- transactions: classify every row
-- txn_classified is transient and holds one row per RAW line with its failed rules.
CREATE OR REPLACE TRANSIENT TABLE txn_classified AS
WITH base AS (
    SELECT r.*,
           m.business_date                                           AS expected_business_date,
           TRY_TO_NUMBER(r.amount, 18, 2)                            AS amount_parsed,
           TRY_TO_TIMESTAMP_NTZ(r.txn_ts, 'YYYY-MM-DD HH24:MI:SS')   AS ts_parsed,
           ROW_NUMBER() OVER (PARTITION BY r.source_file, r.transaction_id
                              ORDER BY r.source_row_number)          AS id_seq
    FROM FINANCE_DB.RAW.raw_transactions r
    JOIN FINANCE_DB.AUDIT.manifest m
      ON m.source_file = r.source_file AND m.file_type = 'transactions'
),
accounts AS (
    SELECT DISTINCT account_id FROM FINANCE_DB.STAGING.stg_accounts
),
flagged AS (
    SELECT b.*,
           (b.id_seq > 1)                                                AS f_duplicate,
           (NULLIF(TRIM(b.account_id), '') IS NULL)                      AS f_missing_account,
           (NULLIF(TRIM(b.account_id), '') IS NOT NULL
              AND a.account_id IS NULL)                                  AS f_orphan_account,
           (b.amount_parsed IS NULL
              OR (b.txn_type =  'REFUND' AND b.amount_parsed >= 0)
              OR (b.txn_type <> 'REFUND' AND b.amount_parsed <= 0))      AS f_invalid_amount,
           (b.currency IS DISTINCT FROM 'INR')                           AS f_invalid_currency,
           (b.ts_parsed IS NULL
              OR TO_DATE(b.ts_parsed) <> b.expected_business_date)       AS f_ts_outside_business_date
    FROM base b
    LEFT JOIN accounts a ON a.account_id = b.account_id
)
SELECT f.*,
       ARRAY_CONSTRUCT_COMPACT(
           IFF(f_duplicate,              'duplicate_transaction_id', NULL),
           IFF(f_missing_account,        'missing_account_id',       NULL),
           IFF(f_orphan_account,         'orphan_account_id',        NULL),
           IFF(f_invalid_amount,         'invalid_amount',           NULL),
           IFF(f_invalid_currency,       'invalid_currency',         NULL),
           IFF(f_ts_outside_business_date, 'ts_outside_business_date', NULL)
       ) AS dq_rules
FROM flagged f;

-- ------------------------------------------------- transactions: split and load
INSERT OVERWRITE INTO stg_transactions
SELECT transaction_id, account_id, merchant_id, ts_parsed, amount_parsed, currency, txn_type,
       channel, expected_business_date, source_file, source_row_number, load_id, loaded_at
FROM txn_classified
WHERE ARRAY_SIZE(dq_rules) = 0;

INSERT OVERWRITE INTO quarantine_transactions
SELECT transaction_id, account_id, merchant_id, txn_ts, amount, currency, txn_type, channel,
       expected_business_date, source_file, source_row_number,
       GET(dq_rules, 0)::VARCHAR, dq_rules, load_id, SYSDATE()
FROM txn_classified
WHERE ARRAY_SIZE(dq_rules) > 0;

-- Quick look at the result: rows staged and quarantined, by rule.
SELECT dq_rule, COUNT(*) AS quarantined_rows
FROM quarantine_transactions
GROUP BY dq_rule
ORDER BY dq_rule;
