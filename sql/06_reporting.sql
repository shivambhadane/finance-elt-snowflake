-- REPORTING layer: facts, dimensions and summaries, built from STAGING only.
-- Rebuilt on each run (CREATE OR REPLACE), so re-running is safe.
USE ROLE SYSADMIN;
USE WAREHOUSE FINANCE_WH;
USE SCHEMA FINANCE_DB.REPORTING;

-- Dimensions: one row per key, as staged.
CREATE OR REPLACE TABLE dim_customer AS
SELECT customer_id, full_name, email, city, state, segment, created_date
FROM FINANCE_DB.STAGING.stg_customers;

CREATE OR REPLACE TABLE dim_account AS
SELECT account_id, customer_id, account_type, branch_code, opened_date, status
FROM FINANCE_DB.STAGING.stg_accounts;

CREATE OR REPLACE TABLE dim_merchant AS
SELECT merchant_id, merchant_name, category, city
FROM FINANCE_DB.STAGING.stg_merchants;

-- Fact: one row per clean transaction. amount is signed; refunds are negative (D1),
-- so SUM(amount) is net spend.
CREATE OR REPLACE TABLE fct_transactions AS
SELECT transaction_id, account_id, merchant_id, txn_ts, business_date,
       amount, currency, txn_type, channel
FROM FINANCE_DB.STAGING.stg_transactions;

-- Daily summary by transaction type and channel.
CREATE OR REPLACE TABLE rpt_daily_summary AS
SELECT business_date,
       txn_type,
       channel,
       COUNT(*)                                       AS txn_count,
       SUM(amount)                                    AS net_amount,
       SUM(IFF(amount > 0, amount, 0))                AS positive_amount,
       SUM(IFF(amount < 0, amount, 0))                AS negative_amount
FROM fct_transactions
GROUP BY business_date, txn_type, channel;

-- Check: the summary must add up to the fact table.
SELECT (SELECT COUNT(*) FROM fct_transactions)              AS fact_rows,
       (SELECT SUM(txn_count) FROM rpt_daily_summary)       AS summary_rows,
       (SELECT SUM(amount) FROM fct_transactions)           AS fact_net,
       (SELECT SUM(net_amount) FROM rpt_daily_summary)      AS summary_net;
