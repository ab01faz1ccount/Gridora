from __future__ import annotations

import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import Operation, SheetRangeTarget
from ops_for_tests import build_registry

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError


def make_ctx() -> FakeExecContext:
    ctx = FakeExecContext()
    ctx.fill([[txt("name"), txt("score")], [txt("ali"), num(1)], [txt("sara"), num(2)], [None, num(3)]])
    return ctx


def op(ctx: FakeExecContext, type_: str = "t_case", r1: int = 3, c1: int = 1, **params: object) -> Operation:
    return Operation(type=type_, target=SheetRangeTarget(range=ctx.rng(0, 0, r1, c1)),
                     params={"column": "name", **params})


@pytest.fixture
def ex() -> DataOpsExecutor:
    return DataOpsExecutor(build_registry())


def test_apply_changes_cells_and_returns_cell_patch(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    res = ex.apply(op(ctx), ctx)
    assert res.status == "ok" and res.delta is not None and res.delta.kind == "cell_patch"
    assert ctx.grid[(1, 0)].v == txt("ALI") and ctx.grid[(2, 0)].v == txt("SARA")
    assert ctx.writes == 1  # one write, one delta


def test_undo_redo_restores_exact_state(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    original = ctx.snapshot()
    res = ex.apply(op(ctx), ctx)
    after = ctx.snapshot()
    assert after != original
    ctx.apply_delta(res.delta, inverse=True)
    assert ctx.snapshot() == original
    ctx.apply_delta(res.delta, inverse=False)
    assert ctx.snapshot() == after


def test_preview_never_mutates(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    before = ctx.snapshot()
    pv = ex.preview(op(ctx), ctx, limit=2)
    assert ctx.snapshot() == before and ctx.writes == 0
    assert pv.columns == ["name", "score"] and pv.rows == [["ALI", 1.0], ["SARA", 2.0]] and pv.total_rows == 3


def test_apply_is_deterministic(ex: DataOpsExecutor) -> None:
    a, b = make_ctx(), make_ctx()
    ex.apply(op(a), a)
    ex.apply(op(b), b)
    assert a.snapshot() == b.snapshot()


def test_shrinking_result_clears_trailing_rows_in_one_delta(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    original = ctx.snapshot()
    res = ex.apply(op(ctx, "t_drop_empty"), ctx)
    assert res.status == "ok" and res.affected.rows == 2
    assert (3, 0) not in ctx.grid and (3, 1) not in ctx.grid  # old last row cleared
    assert ctx.writes == 1
    ctx.apply_delta(res.delta, inverse=True)
    assert ctx.snapshot() == original


def test_result_needing_extra_space_fails_when_occupied(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    ctx.put(0, 2, txt("keep me"))
    before = ctx.snapshot()
    res = ex.apply(op(ctx, "t_widen"), ctx)
    assert res.status == "error" and res.errors[0].code == "would_overwrite"
    assert ctx.snapshot() == before and ctx.writes == 0


def test_result_needing_extra_space_succeeds_when_free(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    res = ex.apply(op(ctx, "t_widen"), ctx)
    assert res.status == "ok" and ctx.grid[(1, 2)].v == txt("x")


def test_formulas_are_never_silently_converted(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    ctx.put(1, 1, num(1), f="=A1+1")
    before = ctx.snapshot()
    res = ex.apply(op(ctx), ctx)
    assert res.status == "error" and res.errors[0].code == "range_has_formulas"
    assert ctx.snapshot() == before
    # explicit, confirmed opt-in is the only way through
    res = ex.apply(op(ctx, formulas="convert_to_values"), ctx)
    assert res.status == "ok" and ctx.grid[(1, 1)].f is None


def test_error_values_are_refused(ex: DataOpsExecutor) -> None:
    from gridora_contracts.models import ErrValue
    ctx = make_ctx()
    ctx.put(1, 1, ErrValue(e="#N/A"))
    res = ex.apply(op(ctx), ctx)
    assert res.status == "error" and res.errors[0].code == "range_has_error_values"


def test_mixed_column_types_are_refused(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    ctx.put(2, 1, txt("oops"))
    res = ex.apply(op(ctx), ctx)
    assert res.status == "error" and res.errors[0].code == "mixed_column_types"


def test_cap_on_cells_per_patch(ex: DataOpsExecutor) -> None:
    small = DataOpsExecutor(build_registry(), max_patch_cells=4)
    ctx = make_ctx()
    res = small.apply(op(ctx), ctx)
    assert res.status == "error" and res.errors[0].code == "too_large_for_history" and ctx.writes == 0


def test_duplicate_and_blank_headers_get_deterministic_names(ex: DataOpsExecutor) -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("a"), txt("a"), None], [txt("x"), txt("y"), txt("z")]])
    pv = ex.preview(Operation(type="t_case", target=SheetRangeTarget(range=ctx.rng(0, 0, 1, 2)),
                              params={"column": "a_2"}), ctx, 10)
    assert pv.columns == ["a", "a_2", "column_3"] and pv.rows == [["x", "Y", "z"]]


# ------------------------------------------------------------ validation
def codes(errs: list) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    return [(e.code, e.path) for e in errs]


def test_unknown_operation(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    assert codes(ex.validate(op(ctx, "nope"))) == [("unknown_operation", "/type")]


def test_param_errors_have_paths_relative_to_operation_root(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    errs = ex.validate(op(ctx, mode="shout", bogus=1))
    got = set(codes(errs))
    assert ("invalid_param", "/params/mode") in got and ("unknown_param", "/params/bogus") in got


def test_static_rule_errors_are_reported(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    assert ("invalid_param", "/params/mode") in codes(ex.validate(op(ctx, "t_bad")))


def test_unknown_column_needs_ctx_and_points_at_the_field(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    o = op(ctx, column="missing", keys=["name", "nope"])
    assert ex.validate(o) == []  # static validation has no data
    got = codes(ex.validate(o, ctx))
    assert ("unknown_column", "/params/column") in got and ("unknown_column", "/params/keys/1") in got
    res = ex.apply(o, ctx)
    assert res.status == "error" and ctx.writes == 0


def test_preview_raises_with_all_errors(ex: DataOpsExecutor) -> None:
    ctx = make_ctx()
    with pytest.raises(DataOpsError) as e:
        ex.preview(op(ctx, column="missing"), ctx, 5)
    assert e.value.code == "validation_failed" and e.value.errors[0].code == "unknown_column"


def test_data_table_target_without_a_store_is_a_typed_error(ex: DataOpsExecutor) -> None:
    from gridora_contracts.models import DataTableTarget
    o = Operation(type="t_case", target=DataTableTarget(table_id="t1"), params={"column": "a"})
    res = ex.apply(o, make_ctx())
    assert res.status == "error" and res.errors[0].code == "not_implemented"


def test_empty_pipeline_is_a_no_op(ex: DataOpsExecutor) -> None:
    from gridora_contracts.models import Pipeline
    ctx = make_ctx()
    assert ex.run_pipeline(Pipeline(name="p", input_kind="sheet_range", steps=[]),
                           SheetRangeTarget(range=ctx.rng(0, 0, 1, 1)), ctx) == []
