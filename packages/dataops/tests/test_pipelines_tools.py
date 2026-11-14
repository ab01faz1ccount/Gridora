from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import (
    Column,
    DataTableTarget,
    Pipeline,
    PipelineStep,
    SheetRangeTarget,
    TableVersionDelta,
    Tool,
    ToolInput,
)

from gridora_dataops import DataOpsExecutor, ParquetTableStore, create_table_store
from gridora_dataops.errors import DataOpsError

EX = DataOpsExecutor()


def step(type_: str, **params: Any) -> PipelineStep:
    return PipelineStep(type=type_, params=params)


def pipe(kind: str, *steps: PipelineStep) -> Pipeline:
    return Pipeline(name="p", input_kind=kind, steps=list(steps))  # type: ignore[arg-type]


def ph(name: str) -> dict[str, str]:
    return {"$input": name}


# ------------------------------------------------------------ bind_tool
def tool(*steps: PipelineStep, inputs: list[ToolInput] | None = None, kind: str = "sheet_range") -> Tool:
    return Tool(name="t", pipeline=pipe(kind, *steps), inputs=inputs or [])


def test_bind_replaces_placeholders_everywhere_and_leaves_the_tool_untouched() -> None:
    t = tool(step("sort", keys=[{"column": ph("col"), "direction": ph("dir")}]),
             step("remove_duplicates", columns=[ph("col")], keep="first"),
             inputs=[ToolInput(name="col", kind="column", label="c"), ToolInput(name="dir", kind="value", label="d")])
    before = t.model_dump()
    bound = EX.bind_tool(t, {"col": "نام", "dir": "desc"})
    assert bound.steps[0].params == {"keys": [{"column": "نام", "direction": "desc"}]}
    assert bound.steps[1].params == {"columns": ["نام"], "keep": "first"}
    assert t.model_dump() == before and bound.input_kind == "sheet_range"


def test_unbound_optional_input_drops_its_parameter_so_the_default_applies() -> None:
    t = tool(step("sort", keys=[{"column": "a", "direction": ph("dir")}]),
             inputs=[ToolInput(name="dir", kind="value", label="d", required=False)])
    assert EX.bind_tool(t, {}).steps[0].params == {"keys": [{"column": "a"}]}
    assert EX.bind_tool(t, {"dir": None}).steps[0].params == {"keys": [{"column": "a"}]}


def test_bind_errors_are_collected_with_paths() -> None:
    t = tool(step("sort", keys=[{"column": ph("c")}]), step("fill", mode=ph("ghost")),
             inputs=[ToolInput(name="c", kind="column", label="c"), ToolInput(name="r", kind="range", label="r")])
    with pytest.raises(DataOpsError) as e:
        EX.bind_tool(t, {"c": 5, "extra": 1, "r": "A1"})
    got = {(x.code, x.path) for x in e.value.errors}
    assert ("invalid_param", "/inputs/c") in got and ("invalid_param", "/inputs/extra") in got
    assert ("invalid_param", "/inputs/r") in got
    assert ("invalid_param", "/pipeline/steps/1/params/mode") in got
    with pytest.raises(DataOpsError) as e2:
        EX.bind_tool(tool(step("sort", keys=[]), inputs=[ToolInput(name="c", kind="column", label="c")]), {})
    assert e2.value.errors[0].path == "/inputs/c"


# ------------------------------------------------------------ validate_tool
def test_validate_accepts_a_well_formed_tool() -> None:
    t = tool(step("sort", keys=[{"column": ph("col")}]), step("fill", mode="down"),
             inputs=[ToolInput(name="col", kind="column", label="c")])
    assert EX.validate_tool(t, SheetRangeTarget(range=FakeExecContext().rng(0, 0, 1, 1))) == []


def test_validate_reports_each_problem_at_its_place() -> None:
    t = tool(step("sort", keys=[{"column": ph("v")}]),                    # a value input where a column belongs
             step("fill", mode=ph("c")),                                  # a column input where a value belongs
             step("nope"), step("join", left_on=["a"], right_on=["b"]),
             step("remove_duplicates", keep="middle"),                    # plain static error
             inputs=[ToolInput(name="v", kind="value", label="v"), ToolInput(name="c", kind="column", label="c"),
                     ToolInput(name="unused", kind="value", label="u"), ToolInput(name="v", kind="value", label="dup")])
    errs = EX.validate_tool(t, DataTableTarget(table_id="x"))
    got = {(e.code, e.path) for e in errs}
    assert ("invalid_param", "/pipeline/input_kind") in got
    assert ("invalid_param", "/pipeline/steps/0/params/keys/0/column") in got
    assert ("invalid_param", "/pipeline/steps/1/params/mode") in got
    assert ("unknown_operation", "/pipeline/steps/2/type") in got
    assert ("invalid_param", "/pipeline/steps/3/type") in got
    assert ("invalid_param", "/pipeline/steps/4/params/keep") in got
    assert ("invalid_param", "/inputs/unused") in got and ("invalid_param", "/inputs/3/name") in got


def test_validate_checks_first_step_columns_when_a_context_is_given() -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("a"), txt("b")], [num(1), num(2)]])
    tgt = SheetRangeTarget(range=ctx.rng(0, 0, 1, 1))
    t = tool(step("sort", keys=[{"column": "nope"}]), step("sort", keys=[{"column": "also_nope"}]))
    errs = EX.validate_tool(t, tgt, ctx)
    assert [(e.code, e.path) for e in errs] == [("unknown_column", "/pipeline/steps/0/params/keys/0/column")]
    assert ctx.writes == 0


# ------------------------------------------------------------ run_pipeline on a sheet
def sheet() -> FakeExecContext:
    ctx = FakeExecContext()
    ctx.fill([[txt("name"), txt("score")], [txt("  گل رز "), num(3)], [txt("آب"), num(1)], [txt("آب"), num(1)],
              [txt("باران"), num(2)]])
    ctx.put(10, 5, num(7), f="=1+6")  # a formula far outside the range: must never be touched
    return ctx


def test_sheet_pipeline_tracks_the_range_between_steps_and_has_one_undoable_delta_per_step() -> None:
    ctx = sheet()
    original = ctx.snapshot()
    tgt = SheetRangeTarget(range=ctx.rng(0, 0, 4, 1))
    p = pipe("sheet_range",
             step("clean_text"),                                              # trims
             step("remove_duplicates"),                                       # shrinks 4 -> 3 data rows
             step("split_column", column="name", delimiter=" ", merge_delimiters=True),  # grows by a column
             step("sort", keys=[{"column": "score"}]))                        # uses a column of the new shape
    res = EX.run_pipeline(p, tgt, ctx)
    assert [r.status for r in res] == ["ok"] * 4 and ctx.writes == 4
    assert [ctx.grid[(r, 0)].v for r in (1, 2, 3)] == [txt("آب"), txt("باران"), txt("گل")]
    assert ctx.grid[(0, 1)].v == txt("name_2") and ctx.grid[(3, 1)].v == txt("رز")
    assert (4, 0) not in ctx.grid and ctx.grid[(10, 5)].f == "=1+6"
    for r in reversed(res):  # per-step undo restores the original exactly
        ctx.apply_delta(r.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original


def test_a_failing_step_in_the_dry_run_writes_nothing_and_points_at_the_step() -> None:
    ctx = sheet()
    before = ctx.snapshot()
    p = pipe("sheet_range", step("clean_text"), step("sort", keys=[{"column": "score"}]),
             step("sort", keys=[{"column": "nope"}]))
    res = EX.run_pipeline(p, SheetRangeTarget(range=ctx.rng(0, 0, 4, 1)), ctx)
    assert ctx.snapshot() == before and ctx.writes == 0
    assert [r.status for r in res] == ["error"] * 3
    assert (res[2].errors[0].code, res[2].errors[0].path) == ("unknown_column", "/steps/2/params/keys/0/column")
    assert res[0].errors[0].code == "pipeline_aborted"


def test_dry_run_catches_would_overwrite_before_anything_is_written() -> None:
    ctx = sheet()
    ctx.put(0, 2, txt("occupied"))
    before = ctx.snapshot()
    p = pipe("sheet_range", step("clean_text"), step("split_column", column="name", delimiter=" ", merge_delimiters=True))
    res = EX.run_pipeline(p, SheetRangeTarget(range=ctx.rng(0, 0, 4, 1)), ctx)
    assert res[1].errors[0].code == "would_overwrite" and ctx.writes == 0 and ctx.snapshot() == before


class FlakyContext(FakeExecContext):
    """Fails the Nth write_range call (a failure that a dry run cannot foresee)."""

    fail_on = 2
    fail_always_after = False
    _failed = False

    def write_range(self, rng, rows):  # type: ignore[no-untyped-def]
        if self.writes + 1 == self.fail_on and (self.fail_always_after or not self._failed):
            self._failed = True
            raise DataOpsError("version_conflict", "simulated failure")
        if self._failed and self.fail_always_after:
            raise DataOpsError("version_conflict", "still failing")
        return super().write_range(rng, rows)


def test_a_failure_during_commit_rolls_back_earlier_steps() -> None:
    ctx = FlakyContext()
    ctx.fill([[txt("name"), txt("score")], [txt("  گل رز "), num(3)], [txt("آب"), num(1)], [txt("آب"), num(1)]])
    ctx.put(10, 5, num(7), f="=1+6")
    original = ctx.snapshot()
    p = pipe("sheet_range", step("clean_text"), step("remove_duplicates"), step("sort", keys=[{"column": "score"}]))
    # the failure surfaces from apply as a typed result only for DataOpsError; wrap by calling the runner directly
    res = EX.run_pipeline(p, SheetRangeTarget(range=ctx.rng(0, 0, 3, 1)), ctx)
    assert [r.status for r in res] == ["error"] * 3
    assert res[1].errors[0].code == "version_conflict" and res[0].errors[0].code == "pipeline_aborted"
    assert ctx.snapshot() == original  # step 1 was undone, value by value; the far formula was never touched


def test_when_the_rollback_itself_fails_the_result_says_so_and_nothing_raises() -> None:
    ctx = FlakyContext()
    ctx.fail_always_after = True
    ctx.fill([[txt("name"), txt("score")], [txt("  گل رز "), num(3)], [txt("آب"), num(1)]])
    p = pipe("sheet_range", step("clean_text"), step("sort", keys=[{"column": "score"}]))
    res = EX.run_pipeline(p, SheetRangeTarget(range=ctx.rng(0, 0, 2, 1)), ctx)
    assert [e.code for e in res[1].errors] == ["version_conflict", "rollback_incomplete"]


def test_pipeline_guards() -> None:
    ctx = sheet()
    tgt = SheetRangeTarget(range=ctx.rng(0, 0, 4, 1))
    assert EX.run_pipeline(pipe("data_table", step("fill")), tgt, ctx)[0].errors[0].path == "/input_kind"
    assert EX.run_pipeline(pipe("sheet_range", step("sort", keys=[{"column": ph("c")}])), tgt, ctx)[0].errors[0].path == "/steps/0/params"
    assert EX.run_pipeline(pipe("sheet_range", step("join", left_on=["a"], right_on=["a"])), tgt, ctx)[0].errors[0].path == "/steps/0/type"
    res = EX.run_pipeline(pipe("sheet_range", step("fill", has_header=True), step("fill", has_header=False)), tgt, ctx)
    assert res[1].errors[0].path == "/steps/1/params/has_header" and ctx.writes == 0


# ------------------------------------------------------------ run_pipeline on tables
@pytest.fixture
def tctx(tmp_path: Path) -> FakeExecContext:
    def path_for(owner: str, tid: str, v: int) -> Path:
        return tmp_path / owner / tid / f"v{v}.parquet"
    store = create_table_store(path_for, new_id=iter(f"t{i}" for i in range(1, 50)).__next__)
    c = FakeExecContext(store=store)
    store.create_from_rows(c, "sales", [Column(name="city", dtype="string"), Column(name="amount", dtype="float64")],
                           [["  تهران", 10.0], ["کرج", 5.0], ["تهران ", 2.0], ["کرج", 5.0]])
    return c


def test_table_pipeline_writes_one_version_per_step(tctx: FakeExecContext) -> None:
    p = pipe("data_table", step("clean_text"), step("remove_duplicates"), step("sort", keys=[{"column": "amount", "direction": "desc"}]))
    res = EX.run_pipeline(p, DataTableTarget(table_id="t1"), tctx)
    assert [r.delta for r in res] == [TableVersionDelta(table_id="t1", from_version=v, to_version=v + 1) for v in (1, 2, 3)]
    s = tctx.store.for_owner("u1")
    assert s.read_page("t1", 0, 10) == [["تهران", 10.0], ["کرج", 5.0], ["تهران", 2.0]]
    assert s.read_page("t1", 0, 10, version=1)[0] == ["  تهران", 10.0]  # history intact: undo = restore_version


def test_table_pipeline_chains_through_a_step_that_creates_a_table(tctx: FakeExecContext) -> None:
    p = pipe("data_table", step("clean_text"),
             step("group_aggregate", by=["city"], aggregations=[{"fn": "sum", "column": "amount"}]),
             step("sort", keys=[{"column": "sum_amount", "direction": "desc"}]))
    res = EX.run_pipeline(p, DataTableTarget(table_id="t1"), tctx)
    assert [r.status for r in res] == ["ok"] * 3
    assert res[1].output == DataTableTarget(table_id="t2")
    assert res[2].delta == TableVersionDelta(table_id="t2", from_version=1, to_version=2)
    assert tctx.store.for_owner("u1").read_page("t2", 0, 10) == [["تهران", 12.0], ["کرج", 10.0]]


def test_a_failure_during_commit_discards_versions_and_tables_of_this_run(tctx: FakeExecContext,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    orig = ParquetTableStore.write_version

    def flaky(self, owner, table_id, frame, *, parent):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:
            raise DataOpsError("version_conflict", "simulated")
        return orig(self, owner, table_id, frame, parent=parent)
    monkeypatch.setattr(ParquetTableStore, "write_version", flaky)
    p = pipe("data_table", step("clean_text"), step("remove_duplicates"), step("sort", keys=[{"column": "amount"}]))
    res = EX.run_pipeline(p, DataTableTarget(table_id="t1"), tctx)
    assert res[1].errors[0].code == "version_conflict"
    s = tctx.store.for_owner("u1")
    assert s.versions("u1", "t1") == [1]
    monkeypatch.undo()
    assert orig(s, "u1", "t1", s.read_frame("u1", "t1")[0], parent=1).version == 3  # number 2 (written, then discarded) stays retired


def test_sheet_filter_then_sort_chains_into_the_new_table(tctx: FakeExecContext) -> None:
    ctx = FakeExecContext(store=tctx.store)
    ctx.fill([[txt("نام"), txt("نمره")], [txt("گل"), num(3)], [txt("آب"), num(1)], [txt("باران"), num(2)]])
    before = ctx.snapshot()
    p = pipe("sheet_range", step("filter", where={"kind": "condition", "column": "نمره", "op": "gt", "value": 1}),
             step("sort", keys=[{"column": "نام"}]))
    res = EX.run_pipeline(p, SheetRangeTarget(range=ctx.rng(0, 0, 3, 1)), ctx)
    assert [r.status for r in res] == ["ok", "ok"] and ctx.snapshot() == before and ctx.writes == 0
    assert res[0].output == DataTableTarget(table_id="t2")
    assert tctx.store.for_owner("u1").read_page("t2", 0, 10) == [["باران", 2], ["گل", 3]]


def test_a_saved_tool_runs_with_different_bindings(tctx: FakeExecContext) -> None:
    t = tool(step("clean_text"), step("sort", keys=[{"column": ph("by"), "direction": ph("dir")}]),
             inputs=[ToolInput(name="by", kind="column", label="c"), ToolInput(name="dir", kind="value", label="d", required=False)],
             kind="data_table")
    assert EX.validate_tool(t, DataTableTarget(table_id="t1"), tctx) == []
    first = EX.run_pipeline(EX.bind_tool(t, {"by": "amount", "dir": "desc"}), DataTableTarget(table_id="t1"), tctx)
    assert first[1].status == "ok"
    assert tctx.store.for_owner("u1").read_page("t1", 0, 1) == [["تهران", 10.0]]
    second = EX.run_pipeline(EX.bind_tool(t, {"by": "city"}), DataTableTarget(table_id="t1"), tctx)
    assert second[1].status == "ok" and tctx.store.for_owner("u1").read_page("t1", 0, 1) == [["تهران", 10.0]]
    bad = EX.run_pipeline(EX.bind_tool(t, {"by": "nope"}), DataTableTarget(table_id="t1"), tctx)
    assert bad[1].errors[0].path == "/steps/1/params/keys/0/column" and tctx.store.for_owner("u1").versions("u1", "t1") == [1, 2, 3, 4, 5]
