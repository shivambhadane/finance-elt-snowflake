-- Warehouse, database and one schema per layer. Safe to re-run.
-- Run as SYSADMIN (or ACCOUNTADMIN on a trial account).
USE ROLE SYSADMIN;

-- XSMALL with a 60s auto-suspend keeps trial credit use low.
CREATE WAREHOUSE IF NOT EXISTS FINANCE_WH
    WAREHOUSE_SIZE = XSMALL
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS FINANCE_DB;
CREATE SCHEMA IF NOT EXISTS FINANCE_DB.RAW       COMMENT = 'Files as received, all columns VARCHAR, plus audit columns';
CREATE SCHEMA IF NOT EXISTS FINANCE_DB.STAGING   COMMENT = 'Typed, deduplicated, DQ-checked rows and the quarantine';
CREATE SCHEMA IF NOT EXISTS FINANCE_DB.REPORTING COMMENT = 'Facts, dimensions and reporting tables built from STAGING only';
CREATE SCHEMA IF NOT EXISTS FINANCE_DB.AUDIT     COMMENT = 'Manifests and load log (reconciliation results)';
