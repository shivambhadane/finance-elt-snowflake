-- File format and the external stage that points at the Blob container.
-- Replace the <placeholders> in a Snowsight worksheet; never commit a real SAS token.
--
-- SAS token: Storage account > Containers > <container> > Shared access tokens,
-- permissions Read + List, expiry after 2 Dec 2026. Paste it without the leading '?'.
USE ROLE SYSADMIN;
USE WAREHOUSE FINANCE_WH;
USE SCHEMA FINANCE_DB.RAW;

CREATE FILE FORMAT IF NOT EXISTS csv_with_header
    TYPE = CSV
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    EMPTY_FIELD_AS_NULL = TRUE
    ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE;

-- The stage URL is the container root, so METADATA$FILENAME matches the
-- source_file values in manifest.csv (e.g. transactions/business_date=.../x.csv).
CREATE OR REPLACE STAGE landing_stage
    URL = 'azure://<storage_account>.blob.core.windows.net/<container>/'
    CREDENTIALS = (AZURE_SAS_TOKEN = '<sas_token>')
    FILE_FORMAT = csv_with_header;

-- Expect 3 dimension files, 30 transaction files and 31 manifest.csv files.
LIST @landing_stage;
