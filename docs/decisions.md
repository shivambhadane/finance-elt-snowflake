# Design decisions

Short records of choices that the PRD left open or that someone reviewing the code would ask about.

## D1. Refunds carry negative amounts
Refunds are stored as negative amounts, so summing `amount` gives net spend with no special cases. The `invalid_amount` rule fails a row when a non-refund has `amount <= 0` or a refund has `amount >= 0`. The generator only injects the first case (non-refunds with zero or negative amounts).

## D2. Timestamps are IST with no offset
`txn_ts` is written as `YYYY-MM-DD HH:MM:SS` in Indian Standard Time, and a file's business date is the IST calendar date. Storing an offset and converting would risk moving late-evening transactions into the next day. Audit timestamps (`loaded_at`) are UTC.

## D3. A duplicate is the later copy
A duplicate is an exact copy of an earlier line in the same file. The first occurrence (lowest `source_row_number`) is kept and later copies are quarantined as `duplicate_transaction_id`. Transaction ids are unique across files, so duplicates never span two days.

## D4. Each dirty row breaks exactly one rule
This keeps "dirty rows caught = 100%" exact: every ground-truth row maps to one expected `dq_rule`. STAGING should still check every rule on every row, because real data can break several at once. Count rows lost between layers by distinct source line, not by quarantine rows.

## D5. One manifest per folder, uploaded last
Each business-date folder holds its data file and a one-row `manifest.csv` (the control file). The upload script writes the manifest after the data, so an ADF storage event trigger on `manifest.csv` only fires when the day is complete. `dimensions/` has its own manifest too. The manifest also records a SHA-256 of each file.

## D6. load_log keeps one row per attempt
The PRD gives `source_file` as the key of `AUDIT.load_log`. Instead, each load attempt gets its own `load_id` row, so a failed load followed by a fixed re-run stays visible. The latest row per `source_file` is that file's current status.

## D7. Ground truth is never uploaded
`data/ground_truth/dirty_rows.csv` is the answer key for the DQ checks. It stays local (and can be loaded into AUDIT for the success metric) so the pipeline can't accidentally use it to decide what is dirty.

## Open
- **Where PySpark runs** (blocking before R4). Decide before Sprint 3.
- **Does `METADATA$FILE_ROW_NUMBER` count the header line?** Check 3 in `sql/manual/load_first_day.sql` answers this on the first load. Ground truth numbers data lines from 1.
