-- Load the three dimension files into RAW by hand. Like load_first_day.sql, this is
-- idempotent: each file's rows are deleted and reloaded in one transaction, so a
-- re-run replaces them instead of doubling them. ADF takes this over in Sprint 2.
-- Each file gets its own load_id, because AUDIT.load_log has one row per load_id (D6).
USE ROLE SYSADMIN;
USE WAREHOUSE FINANCE_WH;
USE SCHEMA FINANCE_DB.RAW;

SET customers_load_id = UUID_STRING();
SET accounts_load_id  = UUID_STRING();
SET merchants_load_id = UUID_STRING();

BEGIN;

DELETE FROM raw_customers WHERE source_file = 'dimensions/customers.csv';
COPY INTO raw_customers
    (customer_id, full_name, email, city, state, segment, created_date, source_file, source_row_number)
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER
    FROM @landing_stage/dimensions/customers.csv
)
FORCE = TRUE;
UPDATE raw_customers SET load_id = $customers_load_id, loaded_at = SYSDATE()
WHERE source_file = 'dimensions/customers.csv' AND load_id IS NULL;

DELETE FROM raw_accounts WHERE source_file = 'dimensions/accounts.csv';
COPY INTO raw_accounts
    (account_id, customer_id, account_type, branch_code, opened_date, status, source_file, source_row_number)
FROM (
    SELECT $1, $2, $3, $4, $5, $6, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER
    FROM @landing_stage/dimensions/accounts.csv
)
FORCE = TRUE;
UPDATE raw_accounts SET load_id = $accounts_load_id, loaded_at = SYSDATE()
WHERE source_file = 'dimensions/accounts.csv' AND load_id IS NULL;

DELETE FROM raw_merchants WHERE source_file = 'dimensions/merchants.csv';
COPY INTO raw_merchants
    (merchant_id, merchant_name, category, city, source_file, source_row_number)
FROM (
    SELECT $1, $2, $3, $4, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER
    FROM @landing_stage/dimensions/merchants.csv
)
FORCE = TRUE;
UPDATE raw_merchants SET load_id = $merchants_load_id, loaded_at = SYSDATE()
WHERE source_file = 'dimensions/merchants.csv' AND load_id IS NULL;

COMMIT;

-- Expect 20,000 customers, 30,000 accounts and 2,000 merchants with the default config.
SELECT 'customers' AS dim, COUNT(*) AS rows_loaded FROM raw_customers
UNION ALL SELECT 'accounts', COUNT(*) FROM raw_accounts
UNION ALL SELECT 'merchants', COUNT(*) FROM raw_merchants;
