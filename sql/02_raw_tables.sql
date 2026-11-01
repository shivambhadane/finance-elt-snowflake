-- RAW layer: one row per line in a source file, every source column as VARCHAR so
-- nothing is rejected on load. Data quality is checked later, in STAGING.
--
-- Audit columns on every RAW table:
--   source_file        path of the file inside the container (METADATA$FILENAME)
--   source_row_number  line in that file (METADATA$FILE_ROW_NUMBER)
--   loaded_at          UTC time of the load
--   load_id            one id per load run; matches AUDIT.load_log.load_id
-- loaded_at and load_id are set in the same transaction as the COPY (see
-- sql/manual/load_first_day.sql), so committed rows always have them.
USE ROLE SYSADMIN;
USE SCHEMA FINANCE_DB.RAW;

CREATE TABLE IF NOT EXISTS raw_transactions (
    transaction_id    VARCHAR,
    account_id        VARCHAR,
    merchant_id       VARCHAR,
    txn_ts            VARCHAR,
    amount            VARCHAR,
    currency          VARCHAR,
    txn_type          VARCHAR,
    channel           VARCHAR,
    source_file       VARCHAR NOT NULL,
    source_row_number NUMBER  NOT NULL,
    loaded_at         TIMESTAMP_NTZ,
    load_id           VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_customers (
    customer_id       VARCHAR,
    full_name         VARCHAR,
    email             VARCHAR,
    city              VARCHAR,
    state             VARCHAR,
    segment           VARCHAR,
    created_date      VARCHAR,
    source_file       VARCHAR NOT NULL,
    source_row_number NUMBER  NOT NULL,
    loaded_at         TIMESTAMP_NTZ,
    load_id           VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_accounts (
    account_id        VARCHAR,
    customer_id       VARCHAR,
    account_type      VARCHAR,
    branch_code       VARCHAR,
    opened_date       VARCHAR,
    status            VARCHAR,
    source_file       VARCHAR NOT NULL,
    source_row_number NUMBER  NOT NULL,
    loaded_at         TIMESTAMP_NTZ,
    load_id           VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_merchants (
    merchant_id       VARCHAR,
    merchant_name     VARCHAR,
    category          VARCHAR,
    city              VARCHAR,
    source_file       VARCHAR NOT NULL,
    source_row_number NUMBER  NOT NULL,
    loaded_at         TIMESTAMP_NTZ,
    load_id           VARCHAR
);
