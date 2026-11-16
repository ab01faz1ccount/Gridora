"""The row-major and the columnar sheet paths must give identical results and identical undo (contract v0.4.0, ADR-014).

Every operation runs on the same sheet through both doubles; we compare status, errors, warnings, delta, the final
grid and the grid after undo. Counters prove the columnar path was really taken (no silent fallback).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fakes import ColumnarFakeExecContext, RowFakeExecContext, num, txt
from gridora_contracts.models import (
    BoolValue,
    DataTableTarget,
    DateValue,
    ErrValue,
    Operation,
    SheetRangeTarget,
)

from gridora_dataops import DataOpsExecutor, create_table_store

HEADER = ["name", "city", "qty", "price", "active", "created", "note", "tags"]
ROWS: list[list[Any]] = [
    [txt("علی رضایی"), txt("تهران"), num(3), num(10.5), BoolValue(b=True), DateValue(iso="2024-03-20"), txt(" x  y "), txt("الف,ب,پ")],
    [txt("سارا احمدی"), txt("كرج"), num(1), num(2.0), BoolValue(b=False), DateValue(iso="2024-03-21"), None, txt("ب")],
    [txt("علی رضایی"), txt("تهران"), num(3), num(10.5), BoolValue(b=True), DateValue(iso="2024-03-20"), txt(" x  y "), txt("الف,ب,پ")],
    [txt("مریم"), None, None, num(7.25), None, None, txt("۱۲۳"), None],
    [txt("آب"), txt("قم"), num(5), None, BoolValue(b=False), DateValue(iso="2025-03-20"), txt("متن"), txt("ت,ث")],
    [txt("باران"), txt("تهران"), num(2), num(1.0), BoolValue(b=True), DateValue(iso="1999-12-31"), None, txt("الف")],
]
CASES: list[tuple[str, dict[str, Any]]] = [
    ("sort", {"keys": [{"column": "name"}, {"column": "price", "direction": "desc"}]}),
    ("remove_duplicates", {}),
    ("remove_duplicates", {"columns": ["name", "city"], "keep": "last", "ignore_variants": True}),
    ("change_type", {"column": "qty", "to": "string"}),
    ("find_replace", {"find": "تهران", "replace": "کرج", "columns": ["city"]}),
    ("fill", {"mode": "down"}),
    ("fill", {"mode": "constant", "columns": ["city"], "value": "نامشخص"}),
    ("clean_text", {"collapse_spaces": True, "digits": "to_latin", "arabic_letters_to_persian": True}),
    ("split_column", {"column": "tags", "delimiter": ","}),
    ("merge_columns", {"columns": ["name", "city"], "separator": " - ", "output_name": "full"}),
    ("computed_column", {"name": "total", "expr": {"kind": "call", "fn": "mul", "args": [
        {"kind": "col", "name": "qty"}, {"kind": "col", "name": "price"}]}}),
    ("convert_calendar", {"column": "created", "digits": "latin"}),
    ("convert_calendar", {"column": "created", "format": "parts"}),
    ("filter", {"where": {"kind": "condition", "column": "qty", "op": "ge", "value": 2}}),
    ("group_aggregate", {"by": ["city"], "aggregations": [{"fn": "sum", "column": "price"}, {"fn": "count"}]}),
    ("pivot", {"index": ["name"], "columns": "city", "values": "qty", "fn": "sum"}),
    ("unpivot", {"id_columns": ["name"], "value_columns": ["qty", "price"]}),
]


def make(cls: type, tmp: Path, *, header: bool = True, rows: list[list[Any]] | None = None) -> Any:
    seq = iter(f"t{i}" for i in range(1, 40))
    store = create_table_store(lambda o, t, v: tmp / o / t / f"v{v}.parquet", new_id=seq.__next__)
    ctx = cls(store=store)
    grid = ([[txt(h) for h in HEADER]] if header else []) + (rows if rows is not None else ROWS)
    ctx.fill(grid)
    return ctx


def run(ctx: Any, type_: str, params: dict[str, Any], *, header: bool = True, columnar: bool = True,
        extra: bool = False) -> dict[str, Any]:
    n = len(ctx.grid) and (max(r for r, _ in ctx.grid) + 1)
    rng = ctx.rng(0, 0, n - 1, len(HEADER) - 1)
    body = dict(params)
    if not header:
        body["has_header"] = False
    op = Operation(type=type_, target=SheetRangeTarget(range=rng), params=body,
                   extra_targets=[DataTableTarget(table_id="t1")] if extra else [])
    ex = DataOpsExecutor(columnar=columnar)
    before = ctx.snapshot()
    res = ex.apply(op, ctx)
    after = ctx.snapshot()
    out: dict[str, Any] = {"res": res.model_dump(), "grid": {k: v.model_dump() for k, v in after.items()}}
    if res.delta is not None and res.delta.kind == "cell_patch":
        ctx.apply_delta(res.delta, inverse=True)
        out["undone_equals_original"] = ctx.snapshot() == before
    if res.output is not None:
        out["table"] = ctx.store.for_owner("u1").read_page(res.output.table_id, 0, 100)  # type: ignore[union-attr]
    return out


@pytest.mark.parametrize(("type_", "params"), CASES, ids=[f"{t}-{i}" for i, (t, _) in enumerate(CASES)])
def test_every_operation_gives_identical_results_and_undo_on_both_paths(type_: str, params: dict[str, Any],
                                                                        tmp_path: Path) -> None:
    row = make(RowFakeExecContext, tmp_path / "row")
    col = make(ColumnarFakeExecContext, tmp_path / "col")
    a, b = run(row, type_, params), run(col, type_, params)
    assert a == b
    assert a["res"]["status"] == "ok", a["res"]["errors"]
    assert col.columnar_reads >= 1 and row.reads >= 1
    assert col.reads == 0, "the columnar path must not fall back to read_range"
    if "undone_equals_original" in a:
        assert a["undone_equals_original"] is True


def test_the_columnar_write_is_used_when_the_header_is_unchanged_and_skipped_otherwise(tmp_path: Path) -> None:
    for type_, params, expected in [("sort", {"keys": [{"column": "name"}]}, 1), ("fill", {"mode": "down"}, 1),
                                    ("split_column", {"column": "tags", "delimiter": ","}, 0),
                                    ("computed_column", {"name": "t", "expr": {"kind": "col", "name": "qty"}}, 0)]:
        col = make(ColumnarFakeExecContext, tmp_path / type_)
        assert run(col, type_, params)["res"]["status"] == "ok"
        assert col.columnar_writes == expected, type_


def test_sheet_without_a_header_uses_the_columnar_write_and_matches(tmp_path: Path) -> None:
    row = make(RowFakeExecContext, tmp_path / "r", header=False)
    col = make(ColumnarFakeExecContext, tmp_path / "c", header=False)
    p = {"keys": [{"column": "column_1"}, {"column": "column_4", "direction": "desc"}]}
    assert run(row, "sort", p, header=False) == run(col, "sort", p, header=False)
    assert col.columnar_writes == 1 and col.reads == 0


def test_formulas_fall_back_to_the_exact_path_with_the_same_error_and_the_same_opt_in(tmp_path: Path) -> None:
    row = make(RowFakeExecContext, tmp_path / "r")
    col = make(ColumnarFakeExecContext, tmp_path / "c")
    for ctx in (row, col):
        ctx.put(2, 2, num(3), f="=1+2")
    a, b = run(row, "sort", {"keys": [{"column": "name"}]}), run(col, "sort", {"keys": [{"column": "name"}]})
    assert a == b and a["res"]["errors"][0]["code"] == "range_has_formulas"
    assert col.columnar_writes == 0 and col.grid[(2, 2)].f == "=1+2"
    p = {"keys": [{"column": "name"}], "formulas": "convert_to_values"}
    a, b = run(row, "sort", p), run(col, "sort", p)
    assert a == b and a["res"]["status"] == "ok"
    assert all(v["f"] is None for v in b["grid"].values())  # formulas became values, as asked
    assert b["undone_equals_original"] is True  # and undo brings the formula back


def test_mixed_columns_and_error_values_behave_identically(tmp_path: Path) -> None:
    for mutate, code in [(lambda c: c.put(2, 2, txt("oops")), "mixed_column_types"),
                         (lambda c: c.put(3, 3, ErrValue(e="#N/A")), "range_has_error_values")]:
        row = make(RowFakeExecContext, tmp_path / f"r{code}")
        col = make(ColumnarFakeExecContext, tmp_path / f"c{code}")
        mutate(row)
        mutate(col)
        a, b = run(row, "sort", {"keys": [{"column": "name"}]}), run(col, "sort", {"keys": [{"column": "name"}]})
        assert a == b and a["res"]["errors"][0]["code"] == code


def test_a_header_that_would_change_is_rewritten_by_both_paths_identically(tmp_path: Path) -> None:
    for tweak in ("blank", "duplicate", "padded", "number"):
        row = make(RowFakeExecContext, tmp_path / f"r{tweak}")
        col = make(ColumnarFakeExecContext, tmp_path / f"c{tweak}")
        for ctx in (row, col):
            if tweak == "blank":
                ctx.grid.pop((0, 1))
            elif tweak == "duplicate":
                ctx.put(0, 1, txt("name"))
            elif tweak == "padded":
                ctx.put(0, 1, txt("  city "))
            else:
                ctx.put(0, 1, num(2024))
        p = {"keys": [{"column": "name"}]}
        a, b = run(row, "sort", p), run(col, "sort", p)
        assert a == b, tweak
        assert col.columnar_writes == 0 and row.writes == 1  # the header changed, so the exact write was used
        assert a["undone_equals_original"] is True


def test_header_only_and_shrinking_ranges_match(tmp_path: Path) -> None:
    row = make(RowFakeExecContext, tmp_path / "r", rows=[])
    col = make(ColumnarFakeExecContext, tmp_path / "c", rows=[])
    p = {"keys": [{"column": "name"}]}
    assert run(row, "sort", p) == run(col, "sort", p)
    row, col = make(RowFakeExecContext, tmp_path / "r2"), make(ColumnarFakeExecContext, tmp_path / "c2")
    p2 = {"columns": ["name", "city"]}
    a, b = run(row, "remove_duplicates", p2), run(col, "remove_duplicates", p2)
    assert a == b and a["undone_equals_original"] is True


def test_space_needed_beyond_the_range_is_checked_the_same_way(tmp_path: Path) -> None:
    for cls, tag in ((RowFakeExecContext, "r"), (ColumnarFakeExecContext, "c")):
        ctx = make(cls, tmp_path / tag)
        ctx.put(1, 8, txt("occupied"))  # right of the range, row 1
        res = run(ctx, "split_column", {"column": "tags", "delimiter": ","})
        if tag == "r":
            first = res
        else:
            assert res == first and res["res"]["errors"][0]["code"] == "would_overwrite"


def test_bridge_import_and_chart_data_match(tmp_path: Path) -> None:
    from gridora_contracts.models import ChartSeries, ChartSpec
    row, col = make(RowFakeExecContext, tmp_path / "r"), make(ColumnarFakeExecContext, tmp_path / "c")
    rng = row.rng(0, 0, len(ROWS), len(HEADER) - 1)
    pa = row.store.sheet_range_to_table(row, rng, True, preview=True)
    pb = col.store.sheet_range_to_table(col, rng, True, preview=True)
    assert pa.model_dump() == pb.model_dump() and col.reads == 0
    spec = ChartSpec(document_id="d", type="bar", source=SheetRangeTarget(range=rng),
                     series=[ChartSeries(value_col="price", category_col="city", aggregate="sum")])
    assert DataOpsExecutor().chart_data(spec, row) == DataOpsExecutor().chart_data(spec, col)


def test_the_row_path_can_be_forced_even_on_a_columnar_context(tmp_path: Path) -> None:
    col = make(ColumnarFakeExecContext, tmp_path / "c")
    run(col, "sort", {"keys": [{"column": "name"}]}, columnar=False)
    assert col.columnar_reads == 0 and col.columnar_writes == 0 and col.reads >= 1


@pytest.mark.skipif(os.environ.get("GRIDORA_COLUMNAR") == "1", reason="already running the columnar flavour")
def test_the_whole_suite_passes_through_the_columnar_path_too() -> None:
    """Re-runs every other test with each `FakeExecContext` replaced by the columnar double (env GRIDORA_COLUMNAR=1)."""
    here = Path(__file__).parent
    env = {**os.environ, "GRIDORA_COLUMNAR": "1"}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", str(here),
                        "--deselect", f"{__file__}::test_the_whole_suite_passes_through_the_columnar_path_too"],
                       env=env, capture_output=True, text=True, cwd=here.parent, check=False)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-1500:]
