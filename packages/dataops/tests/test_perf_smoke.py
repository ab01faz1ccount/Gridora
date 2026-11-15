"""Smoke test for accidental quadratic behaviour (NOT a benchmark: thresholds are deliberately generous).
The real 100k-row numbers live in BENCHMARKS.md and come from benchmarks/run.py."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fakes import FakeExecContext
from gridora_contracts.models import DataTableTarget, Operation

from gridora_dataops import DataOpsExecutor, create_table_store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from generate import generate

ROWS = 10_000
OPS = [
    ("sort", {"keys": [{"column": "name"}, {"column": "price", "direction": "desc"}]}),
    ("remove_duplicates", {}),
    ("clean_text", {"digits": "to_latin", "arabic_letters_to_persian": True}),
    ("group_aggregate", {"by": ["key"], "aggregations": [{"fn": "sum", "column": "price"}]}),
    ("change_type", {"column": "amount_text", "to": "int64"}),
]


@pytest.mark.parametrize(("type_", "params"), OPS, ids=[o[0] for o in OPS])
def test_ten_thousand_rows_finish_quickly(tmp_path: Path, type_: str, params: dict) -> None:  # type: ignore[type-arg]
    store = create_table_store(lambda o, t, v: tmp_path / o / t / f"v{v}.parquet", new_id=iter(f"t{i}" for i in range(1, 9)).__next__)
    store.create_table("u1", "w1", "t", generate(ROWS))
    ctx = FakeExecContext(store=store)
    op = Operation(type=type_, target=DataTableTarget(table_id="t1"), params=params)
    t0 = time.perf_counter()
    assert DataOpsExecutor().apply(op, ctx).status == "ok"
    assert time.perf_counter() - t0 < 10  # measured ~0.05-0.2 s; 10 s only catches pathologies
