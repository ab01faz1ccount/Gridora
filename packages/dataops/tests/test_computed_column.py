from __future__ import annotations

import datetime as dt
import json

import polars as pl
import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import Operation, SheetRangeTarget
from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.computed_column import MAX_DEPTH, ComputedColumnOp, ComputedParams
from gridora_dataops.spec import PlanEnv

DF = pl.DataFrame({
    "a": [10.0, 4.0, None, 0.0], "b": [2.0, 0.0, 3.0, 5.0], "s": ["علی", " x ", None, "abc"],
    "t": [True, False, None, True], "d": [dt.date(2024, 3, 15), None, dt.date(2020, 1, 1), dt.date(1999, 12, 31)],
})


def lit(v):  # type: ignore[no-untyped-def]
    return {"kind": "lit", "value": v}


def col(n):  # type: ignore[no-untyped-def]
    return {"kind": "col", "name": n}


def call(fn, *args):  # type: ignore[no-untyped-def]
    return {"kind": "call", "fn": fn, "args": list(args)}


def comp(expr, name="r", df=DF):  # type: ignore[no-untyped-def]
    out = ComputedColumnOp().plan(df, ComputedParams.model_validate({"name": name, "expr": expr}), PlanEnv())
    return out.frame[name].to_list(), out


@pytest.mark.parametrize(("expr", "expected"), [
    (call("add", col("a"), lit(1)), [11.0, 5.0, None, 1.0]),
    (call("mul", col("a"), col("b")), [20.0, 0.0, None, 0.0]),
    (call("sub", lit(10), col("b")), [8.0, 10.0, 7.0, 5.0]),
    (call("round", call("div", lit(7), lit(2))), [4.0] * 4),
    (call("neg", col("b")), [-2.0, -0.0, -3.0, -5.0]),
    (call("max2", col("a"), col("b")), [10.0, 4.0, 3.0, 5.0]),
    (call("upper", call("trim", col("s"))), ["علی", "X", None, "ABC"]),
    (call("len", col("s")), [3.0, 3.0, None, 3.0]),
    (call("left", col("s"), lit(2)), ["عل", " x", None, "ab"]),
    (call("right", col("s"), lit(2)), ["لی", "x ", None, "bc"]),
    (call("substring", col("s"), lit(2), lit(5)), ["لی", "x ", None, "bc"]),
    (call("replace", col("s"), lit("x"), lit("Y")), ["علی", " Y ", None, "abc"]),
    (call("concat", col("s"), lit("-"), col("a")), ["علی-10", " x -4", "-", "abc-0"]),
    (call("gt", col("a"), lit(3)), [True, True, None, False]),
    (call("and", call("gt", col("b"), lit(1)), col("t")), [True, False, None, True]),
    (call("not", col("t")), [False, True, None, False]),
    (call("if", call("gt", col("b"), lit(1)), lit("big"), lit("small")), ["big", "small", "big", "big"]),
    (call("is_null", col("a")), [False, False, True, False]),
    (call("coalesce", col("a"), lit(-1)), [10.0, 4.0, -1.0, 0.0]),
    (call("year", col("d")), [2024.0, None, 2020.0, 1999.0]),
    (call("month", col("d")), [3.0, None, 1.0, 12.0]),
    (call("day", col("d")), [15.0, None, 1.0, 31.0]),
    (call("eq", col("d"), col("d")), [True, None, True, True]),
])
def test_functions(expr: dict, expected: list) -> None:  # type: ignore[type-arg]
    assert comp(expr)[0] == expected


def test_division_by_zero_gives_empty_cells_and_a_warning() -> None:
    values, out = comp(call("div", col("a"), col("b")))
    assert values == [5.0, None, None, 0.0]
    assert [(w.code, w.location) for w in out.warnings] == [("division_by_zero", "r")]
    assert comp(call("mod", col("a"), col("b")))[0] == [0.0, None, None, 0.0]
    assert comp(call("add", col("a"), col("b")))[1].warnings == []


@pytest.mark.parametrize(("expr", "code", "path"), [
    (call("add", col("a"), col("s")), "type_mismatch", "/params/expr"),
    (call("add", lit(1), call("upper", col("a"))), "type_mismatch", "/params/expr/args/1"),
    (call("if", col("a"), lit(1), lit(2)), "type_mismatch", "/params/expr"),
    (call("if", col("t"), lit(1), lit("x")), "type_mismatch", "/params/expr"),
    (call("eq", col("a"), col("s")), "type_mismatch", "/params/expr"),
    (call("lt", col("t"), col("t")), "type_mismatch", "/params/expr"),
    (call("year", col("a")), "type_mismatch", "/params/expr"),
    (call("add", lit(1)), "invalid_param", "/params/expr/args"),
    (call("concat", lit("x")), "invalid_param", "/params/expr/args"),
    (call("and", call("not", col("a")), col("t")), "type_mismatch", "/params/expr/args/0"),
])
def test_type_errors_point_at_the_node(expr: dict, code: str, path: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(DataOpsError) as e:
        comp(expr)
    assert (e.value.errors[0].code, e.value.errors[0].path) == (code, path)


def test_existing_name_depth_and_size_limits() -> None:
    with pytest.raises(DataOpsError) as e:
        comp(lit(1), name="a")
    assert e.value.errors[0].path == "/params/name"
    deep = lit(1)
    for _ in range(MAX_DEPTH + 1):
        deep = call("neg", deep)
    with pytest.raises(DataOpsError) as e2:
        comp(deep)
    assert e2.value.code == "invalid_param"
    wide = lit(0)
    for _ in range(60):
        wide = call("add", wide, call("add", lit(1), lit(1)))
    errs = ComputedColumnOp().validate_static(ComputedParams.model_validate({"name": "r", "expr": wide}))
    assert errs and errs[0].path == "/params/expr"


def test_unknown_function_or_extra_field_is_rejected_by_the_schema() -> None:
    for bad in ({"kind": "call", "fn": "eval", "args": []}, {"kind": "call", "fn": "add", "args": [], "code": "x"},
                {"kind": "col", "name": "a", "extra": 1}):
        with pytest.raises(ValueError):
            ComputedParams.model_validate({"name": "r", "expr": bad})


def test_the_schema_has_a_recursive_def_and_no_free_text_expression() -> None:
    schema = ComputedColumnOp().descriptor().params_schema
    text = json.dumps(schema)
    assert "Call" in schema["$defs"] and schema["properties"]["expr"]["x-gridora-widget"] == "expression-builder"
    assert '"eval"' not in text and "script" not in text


def test_unique_output_name() -> None:
    out = comp(lit(1), name="r", df=pl.DataFrame({"x": [1]}))[1].frame
    assert out.columns == ["x", "r"]


def test_unknown_column_inside_the_tree_is_reported_with_its_path() -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("x")], [num(1)]])
    op = Operation(type="computed_column", target=SheetRangeTarget(range=ctx.rng(0, 0, 1, 0)),
                   params={"name": "r", "expr": call("add", lit(1), call("neg", col("nope")))})
    errs = DataOpsExecutor().validate(op, ctx)
    assert [(e.code, e.path) for e in errs] == [("unknown_column", "/params/expr/args/1/args/0/name")]


def test_on_a_sheet_adds_a_column_and_undoes() -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("qty"), txt("price")], [num(2), num(3.5)], [num(4), num(1)]])
    original = ctx.snapshot()
    op = Operation(type="computed_column", target=SheetRangeTarget(range=ctx.rng(0, 0, 2, 1)),
                   params={"name": "total", "expr": call("mul", col("qty"), col("price"))})
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "ok" and ctx.grid[(0, 2)].v == txt("total")
    assert [ctx.grid[(r, 2)].v for r in (1, 2)] == [num(7.0), num(4.0)]
    ctx.apply_delta(res.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original
