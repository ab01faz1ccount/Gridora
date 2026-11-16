"""In-memory hand-off between pipeline steps must change NOTHING observable except speed.

Each pipeline runs twice on identical inputs: with the hand-off (phase 1's planned frames are committed directly) and
with `pipeline_handoff=False` (every step re-reads its input, the previous behaviour). Results, deltas, final data,
per-step undo and rollback must be identical.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fakes import ColumnarFakeExecContext, RowFakeExecContext, num, txt
from gridora_contracts.models import (
    BoolValue,
    Column,
    DataTableTarget,
    DateValue,
    Pipeline,
    PipelineStep,
    SheetRangeTarget,
    TableVersionDelta,
)

from gridora_dataops import DataOpsExecutor, create_table_store
from gridora_dataops.errors import DataOpsError
from gridora_dataops.pipeline import sheet_roundtrip


def step(type_: str, **params: Any) -> PipelineStep:
    return PipelineStep(type=type_, params=params)


def pipe(kind: str, *steps: PipelineStep) -> Pipeline:
    return Pipeline(name="p", input_kind=kind, steps=list(steps))  # type: ignore[arg-type]


SHEET_PIPELINES: list[list[PipelineStep]] = [
    [step("clean_text"), step("remove_duplicates"), step("sort", keys=[{"column": "name"}])],
    [step("change_type", column="qty", to="int64"), step("computed_column", name="t", expr={"kind": "call", "fn": "mul", "args": [
        {"kind": "col", "name": "qty"}, {"kind": "col", "name": "price"}]}), step("sort", keys=[{"column": "t", "direction": "desc"}])],
    [step("clean_text"), step("split_column", column="tags", delimiter=","), step("fill", mode="down"),
     step("sort", keys=[{"column": "name"}])],
    [step("convert_calendar", column="created", digits="latin"), step("find_replace", columns=["created"], find="/", replace="-"),
     step("remove_duplicates", columns=["name"], keep="last")],
    [step("merge_columns", columns=["name", "city"], separator=" - ", output_name="full"), step("sort", keys=[{"column": "full"}]),
     step("change_type", column="qty", to="string")],
    [step("filter", where={"kind": "condition", "column": "qty", "op": "ge", "value": 2}),
     step("group_aggregate", by=["city"], aggregations=[{"fn": "sum", "column": "price"}]), step("sort", keys=[{"column": "sum_price"}])],
    # --- steps whose behaviour depends on the column type a re-read would give (these pin the normalisation):
    [step("change_type", column="qty", to="int64"), step("fill", columns=["qty"], mode="constant", value=2.5)],   # ints become floats on a sheet
    [step("computed_column", name="e", expr={"kind": "lit", "value": None}), step("change_type", column="e", to="float64")],  # all-empty column is text on re-read
    [step("merge_columns", columns=["name", "city"], output_name=" total ", separator="|"), step("sort", keys=[{"column": "total"}])],  # header names are stripped on re-read
]
HEADER = ["name", "city", "qty", "price", "created", "tags", "active"]
ROWS = [
    [txt("  علی رضایی "), txt("تهران"), num(3), num(10.5), DateValue(iso="2024-03-20"), txt("الف,ب"), BoolValue(b=True)],
    [txt("سارا"), txt("كرج"), num(1), num(2.0), DateValue(iso="2024-03-21"), None, BoolValue(b=False)],
    [txt("  علی رضایی "), txt("تهران"), num(3), num(10.5), DateValue(iso="2024-03-20"), txt("الف,ب"), BoolValue(b=True)],
    [txt("مریم"), None, None, num(7.25), None, txt("پ"), None],
    [txt("آب"), txt("قم"), num(5), None, DateValue(iso="2025-03-20"), txt("ت,ث,ج"), BoolValue(b=False)],
]


def sheet(cls: type, tmp: Path) -> Any:
    seq = iter(f"t{i}" for i in range(1, 60))
    ctx = cls(store=create_table_store(lambda o, t, v: tmp / o / t / f"v{v}.parquet", new_id=seq.__next__))
    ctx.fill([[txt(h) for h in HEADER], *ROWS])
    return ctx


def tables(ctx: Any) -> dict[str, Any]:
    s = ctx.store.for_owner("u1")
    out = {}
    root = ctx.store._path_for("u1", "x", 1).parent.parent
    for tid in sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        out[tid] = [s.read_page(tid, 0, 1000, version=v) for v in s.versions("u1", tid)]
    return out


def run(ex: DataOpsExecutor, ctx: Any, p: Pipeline, target: Any) -> dict[str, Any]:
    original = ctx.snapshot()
    res = ex.run_pipeline(p, target, ctx)
    out: dict[str, Any] = {"res": [r.model_dump() for r in res], "grid": {k: v.model_dump() for k, v in ctx.snapshot().items()},
                           "tables": tables(ctx)}
    if all(r.status == "ok" for r in res):  # per-step undo, newest first, must restore the original exactly
        for r in reversed(res):
            if r.delta is not None and r.delta.kind == "cell_patch":
                ctx.apply_delta(r.delta, inverse=True)
        out["undone_equals_original"] = ctx.snapshot() == original
    return out


@pytest.mark.parametrize("cls", [RowFakeExecContext, ColumnarFakeExecContext], ids=["row", "columnar"])
@pytest.mark.parametrize("i", range(len(SHEET_PIPELINES)))
def test_sheet_pipelines_are_identical_with_and_without_hand_off(i: int, cls: type, tmp_path: Path) -> None:
    p = pipe("sheet_range", *SHEET_PIPELINES[i])
    outs = []
    for handoff in (True, False):
        ctx = sheet(cls, tmp_path / str(handoff))
        outs.append(run(DataOpsExecutor(pipeline_handoff=handoff), ctx, p, SheetRangeTarget(range=ctx.rng(0, 0, len(ROWS), len(HEADER) - 1))))
    assert outs[0] == outs[1]
    sheet_steps = [r for r in outs[0]["res"] if r["delta"]["kind"] == "cell_patch"]
    assert len(sheet_steps) == 0 or outs[0]["undone_equals_original"] is True


def table_ctx(tmp: Path) -> Any:
    seq = iter(f"t{i}" for i in range(1, 60))
    store = create_table_store(lambda o, t, v: tmp / o / t / f"v{v}.parquet", new_id=seq.__next__)
    ctx = RowFakeExecContext(store=store)
    store.create_from_rows(ctx, "t", [Column(name=n, dtype=d) for n, d in [
        ("name", "string"), ("city", "string"), ("qty", "int64"), ("price", "float64"), ("created", "date"), ("tags", "string")]],
        [["  علی ", "تهران", 3, 10.5, "2024-03-20", "الف,ب"], ["سارا", "كرج", 1, 2.0, "2024-03-21", None],
         ["  علی ", "تهران", 3, 10.5, "2024-03-20", "الف,ب"], ["مریم", None, None, 7.25, None, "پ"], ["آب", "قم", 5, None, "2025-03-20", "ت,ث"]])
    return ctx


TABLE_PIPELINES: list[list[PipelineStep]] = [
    [step("clean_text"), step("remove_duplicates"), step("sort", keys=[{"column": "name"}]), step("fill", mode="down")],
    [step("split_column", column="tags", delimiter=","), step("change_type", column="qty", to="float64"),
     step("computed_column", name="t", expr={"kind": "call", "fn": "add", "args": [{"kind": "col", "name": "qty"}, {"kind": "col", "name": "price"}]})],
    [step("clean_text"), step("group_aggregate", by=["name"], aggregations=[{"fn": "sum", "column": "price"}]),
     step("sort", keys=[{"column": "sum_price", "direction": "desc"}]), step("computed_column", name="x", expr={"kind": "lit", "value": 1})],
    [step("convert_calendar", column="created", format="parts"), step("unpivot", id_columns=["name"], value_columns=["created_year", "created_month"]),
     step("remove_duplicates")],
    [step("change_type", column="qty", to="float64"), step("group_aggregate", by=["name"], aggregations=[{"fn": "max", "column": "qty"}]),
     step("fill", columns=["max_qty"], mode="constant", value=2.5)],  # whole-number floats become int64 in the created table (one group is empty)
    [step("computed_column", name="e", expr={"kind": "lit", "value": None}), step("change_type", column="e", to="string")],  # Null dtype -> string on write
]


@pytest.mark.parametrize("i", range(len(TABLE_PIPELINES)))
def test_table_pipelines_are_identical_with_and_without_hand_off(i: int, tmp_path: Path) -> None:
    p = pipe("data_table", *TABLE_PIPELINES[i])
    outs = []
    for handoff in (True, False):
        ctx = table_ctx(tmp_path / str(handoff))
        outs.append(run(DataOpsExecutor(pipeline_handoff=handoff), ctx, p, DataTableTarget(table_id="t1", version=1)))
    assert outs[0] == outs[1]


def test_table_hand_off_keeps_one_version_per_step_and_every_version_readable(tmp_path: Path) -> None:
    ctx = table_ctx(tmp_path)
    res = DataOpsExecutor().run_pipeline(pipe("data_table", *TABLE_PIPELINES[0]), DataTableTarget(table_id="t1", version=1), ctx)
    assert [r.delta for r in res] == [TableVersionDelta(table_id="t1", from_version=v, to_version=v + 1) for v in (1, 2, 3, 4)]
    s = ctx.store.for_owner("u1")
    heights = [len(s.read_page("t1", 0, 100, version=v)) for v in (1, 2, 3, 4, 5)]
    assert heights == [5, 5, 4, 4, 4]  # v1 untouched, dedupe drops the one duplicate, sort/fill keep the rows


def test_the_hand_off_really_skips_the_rereads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gridora_dataops.tables.store import ParquetTableStore
    counts = {"n": 0}
    orig = ParquetTableStore.read_frame

    def counting(self, *a, **k):  # type: ignore[no-untyped-def]
        counts["n"] += 1
        return orig(self, *a, **k)
    monkeypatch.setattr(ParquetTableStore, "read_frame", counting)
    for handoff, expected in ((True, 1), (False, 5)):
        counts["n"] = 0
        ctx = table_ctx(tmp_path / str(handoff))
        DataOpsExecutor(pipeline_handoff=handoff).run_pipeline(pipe("data_table", *TABLE_PIPELINES[0]),
                                                                 DataTableTarget(table_id="t1", version=1), ctx)
        assert counts["n"] == expected, handoff  # hand-off: one read (the dry run); without: that read plus one per step


def test_the_memory_guard_falls_back_to_rereading_and_gives_the_same_result(tmp_path: Path) -> None:
    outs = []
    for max_bytes in (10**9, 1):  # 1 byte: nothing may be held
        ctx = table_ctx(tmp_path / str(max_bytes))
        outs.append(run(DataOpsExecutor(handoff_max_bytes=max_bytes), ctx, pipe("data_table", *TABLE_PIPELINES[0]),
                        DataTableTarget(table_id="t1", version=1)))
    assert outs[0] == outs[1]


def test_rollback_after_a_hand_off_commit_failure_is_exact_on_sheets_and_tables(tmp_path: Path,
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    # sheets: the 2nd write fails -> step 1 is undone value by value
    class Flaky(RowFakeExecContext):  # type: ignore[misc,valid-type]
        def write_range(self, rng, rows):  # type: ignore[no-untyped-def]
            if self.writes == 1 and not getattr(self, "_f", False):
                self._f = True
                raise DataOpsError("version_conflict", "simulated")
            return super().write_range(rng, rows)
    ctx = sheet(Flaky, tmp_path / "s")
    original = ctx.snapshot()
    res = DataOpsExecutor().run_pipeline(pipe("sheet_range", *SHEET_PIPELINES[0]),
                                         SheetRangeTarget(range=ctx.rng(0, 0, len(ROWS), len(HEADER) - 1)), ctx)
    assert res[1].errors[0].code == "version_conflict" and ctx.snapshot() == original
    # tables: the 3rd version write fails -> versions 2 and 3 are discarded, numbers stay retired
    from gridora_dataops.tables.store import ParquetTableStore
    calls = {"n": 0}
    orig = ParquetTableStore.write_version

    def flaky_write(self, owner, tid, frame, *, parent):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            raise DataOpsError("version_conflict", "simulated")
        return orig(self, owner, tid, frame, parent=parent)
    monkeypatch.setattr(ParquetTableStore, "write_version", flaky_write)
    tctx = table_ctx(tmp_path / "t")
    res = DataOpsExecutor().run_pipeline(pipe("data_table", *TABLE_PIPELINES[0]), DataTableTarget(table_id="t1", version=1), tctx)
    assert res[2].errors[0].code == "version_conflict"
    assert tctx.store.for_owner("u1").versions("u1", "t1") == [1]


def test_sheet_roundtrip_matches_what_a_reread_gives() -> None:
    df = pl.DataFrame({" a ": [1, 2], "b": [1.5, float("nan")], "c": [None, None], "d": ["x", None], " a  ": [True, False]},
                      schema={" a ": pl.Int64, "b": pl.Float64, "c": pl.Float64, "d": pl.String, " a  ": pl.Boolean})
    out = sheet_roundtrip(df)
    assert out.columns == ["a", "b", "c", "d", "a_2"]
    assert out.dtypes == [pl.Float64, pl.Float64, pl.String, pl.String, pl.Boolean]
    assert out["b"].to_list() == [1.5, None] and out["a"].to_list() == [1.0, 2.0]
