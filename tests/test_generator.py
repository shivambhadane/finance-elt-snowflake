import csv
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from generator.generate import DQ_RULES, Config, generate, sha256_of
from generator.validate import validate

SMALL = Config(days=3, min_rows_per_day=2_000, max_rows_per_day=2_400,
               customers=300, accounts=500, merchants=50)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def file_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256_of(p) for p in sorted(root.rglob("*.csv"))}


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("data")
    generate(SMALL, path)
    return path


def test_validator_finds_no_problems(out):
    assert validate(out) == []


def test_same_seed_gives_identical_files(out, tmp_path):
    generate(SMALL, tmp_path)
    assert file_hashes(tmp_path) == file_hashes(out)


def test_different_seed_gives_different_files(out, tmp_path):
    generate(Config(**{**SMALL.__dict__, "seed": SMALL.seed + 1}), tmp_path)
    assert file_hashes(tmp_path) != file_hashes(out)


def test_layout_has_one_folder_per_business_date(out):
    folders = sorted(p.name for p in (out / "landing" / "transactions").iterdir())
    assert folders == [f"business_date=2026-09-0{d}" for d in (1, 2, 3)]
    for folder in (out / "landing" / "transactions").iterdir():
        assert sorted(p.name for p in folder.iterdir()) == ["manifest.csv", f"transactions_{folder.name[-10:].replace('-', '')}.csv"]


def test_every_rule_is_injected_at_about_one_percent(out):
    truth = read_rows(out / "ground_truth" / "dirty_rows.csv")
    total = sum(len(read_rows(p)) for p in (out / "landing" / "transactions").rglob("transactions_*.csv"))
    assert abs(len(truth) / total - SMALL.dirty_rate) < 0.001
    counts = Counter(g["dq_rule"] for g in truth)
    assert set(counts) == set(DQ_RULES)
    assert max(counts.values()) - min(counts.values()) <= SMALL.days


def test_duplicate_copy_comes_after_its_original(out):
    for g in read_rows(out / "ground_truth" / "dirty_rows.csv"):
        if g["dq_rule"] != "duplicate_transaction_id":
            continue
        rows = read_rows(out / "landing" / g["source_file"])
        lines = [i for i, r in enumerate(rows, start=1) if r["transaction_id"] == g["transaction_id"]]
        assert len(lines) == 2 and lines[1] == int(g["line_number"])
        assert rows[lines[0] - 1] == rows[lines[1] - 1]


def test_transaction_ids_are_unique_across_files(out):
    ids = Counter(r["transaction_id"]
                  for p in (out / "landing" / "transactions").rglob("transactions_*.csv") for r in read_rows(p))
    duplicates = sum(n - 1 for n in ids.values())
    truth = read_rows(out / "ground_truth" / "dirty_rows.csv")
    assert duplicates == sum(g["dq_rule"] == "duplicate_transaction_id" for g in truth)


def test_default_config_produces_over_a_million_rows():
    cfg = Config()
    assert cfg.days * cfg.min_rows_per_day >= 1_000_000
    assert cfg.start_date == date(2026, 9, 1)
