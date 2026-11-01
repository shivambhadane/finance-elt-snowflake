"""Upload the generated landing folder to Azure Blob Storage, keeping its layout.

Within each folder the data files go first and manifest.csv goes last, so an ADF
storage event trigger on manifest.csv only fires once the day's data is complete.
ground_truth/ is never uploaded.

    export AZURE_STORAGE_CONNECTION_STRING="..."   # Storage account > Access keys
    python scripts/upload_to_blob.py --container landing                  # everything
    python scripts/upload_to_blob.py --container landing --date 2026-09-01  # one day
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from azure.storage.blob import BlobServiceClient


def upload_order(landing: Path, business_date: str | None) -> list[Path]:
    if business_date:
        folders = [landing / "transactions" / f"business_date={business_date}"]
    else:
        folders = [landing / "dimensions", *sorted((landing / "transactions").iterdir())]
    files = []
    for folder in folders:
        if not folder.is_dir():
            sys.exit(f"Not found: {folder}. Run `python -m generator` first.")
        data = sorted(p for p in folder.glob("*.csv") if p.name != "manifest.csv")
        files += [*data, folder / "manifest.csv"]
    return files


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--container", required=True)
    p.add_argument("--landing", type=Path, default=Path("data/landing"))
    p.add_argument("--date", help="upload only this business date (YYYY-MM-DD)")
    args = p.parse_args()

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        sys.exit("Set AZURE_STORAGE_CONNECTION_STRING first.")
    container = BlobServiceClient.from_connection_string(conn).get_container_client(args.container)
    if not container.exists():
        container.create_container()

    for path in upload_order(args.landing, args.date):
        blob_name = path.relative_to(args.landing).as_posix()
        with path.open("rb") as f:
            container.upload_blob(blob_name, f, overwrite=True)
        print(f"uploaded {blob_name}")


if __name__ == "__main__":
    main()
