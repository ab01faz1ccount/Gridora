"""Formulas are never turned into values silently, and the user CAN confirm it (the `formulas` parameter)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fakes import ColumnarFakeExecContext, RowFakeExecContext, num, txt
from gridora_contracts.models import DateValue, Operation, SheetRangeTarget

from gridora_dataops import DataOpsExecutor, create_table_store

IN_PLACE: list[tuple[str, dict[str, Any]]] = [
    ("sort", {"keys": [{"column": "name"}]}),
    ("remove_duplicates", {}),
    ("change_type", {"column": "score", "to": "string"}),
    ("find_replace", {"find": "a", "replace": "b"}),
    ("fill", {"mode": "down"}),
    ("clean_text", {}),
    ("split_column", {"column": "tags", "delimiter": ","}),
    ("merge_columns", {"columns": ["name", "tags"], "output_name": "m"}),
    ("computed_column", {"name": "t", "expr": {"kind": "col", "name": "score"}}),
    ("convert_calendar", {"column": "when"}),
]
TABLE_MAKING: list[tuple[str, dict[str, Any]]] = [
    ("filter", {"where": {"kind": "condition", "column": "score", "op": "ge", "value": 0}}),
    ("group_aggregate", {"by": ["name"], "aggregations": [{"fn": "sum", "column": "score"}]}),
    ("pivot", {"index": ["name"], "columns": "tags", "values": "score", "fn": "sum"}),
    ("unpivot", {"id_columns": ["name"], "value_columns": ["score"]}),
]


def sheet(cls: type, tmp: Path) -> Any:
    seq = iter(f"t{i}" for i in range(1, 20))
    ctx = cls(store=create_table_store(lambda o, t, v: tmp / o / t / f"v{v}.parquet", new_id=seq.__next__))
    ctx.fill([[txt("name"), txt("score"), txt("when"), txt("tags")],
              [txt("a"), num(1), DateValue(iso="2024-03-20"), txt("x,y")],
              [txt("b"), num(2), DateValue(iso="2024-03-21"), txt("z")]])
    ctx.put(1, 1, num(1), f="=0+1")  # a formula in the data
    return ctx


@pytest.mark.parametrize("cls", [RowFakeExecContext, ColumnarFakeExecContext], ids=["row", "columnar"])
@pytest.mark.parametrize(("type_", "params"), IN_PLACE, ids=[t for t, _ in IN_PLACE])
def test_in_place_operations_refuse_formulas_unless_confirmed(type_: str, params: dict[str, Any], cls: type,
                                                              tmp_path: Path) -> None:
    ctx = sheet(cls, tmp_path)
    original = ctx.snapshot()
    ex = DataOpsExecutor()
    op = Operation(type=type_, target=SheetRangeTarget(range=ctx.rng(0, 0, 2, 3)), params=params)
    res = ex.apply(op, ctx)
    assert res.status == "error" and res.errors[0].code == "range_has_formulas"
    assert ctx.writes == 0 and ctx.snapshot() == original
    ok = ex.apply(op.model_copy(update={"params": {**params, "formulas": "convert_to_values"}}), ctx)
    assert ok.status == "ok" and ctx.writes == 1
    assert all(c.f is None for c in ctx.grid.values())  # the formula became its value
    ctx.apply_delta(ok.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original and ctx.grid[(1, 1)].f == "=0+1"  # undo brings the formula back


@pytest.mark.parametrize(("type_", "params"), TABLE_MAKING, ids=[t for t, _ in TABLE_MAKING])
def test_operations_that_only_read_the_range_accept_formulas(type_: str, params: dict[str, Any], tmp_path: Path) -> None:
    ctx = sheet(ColumnarFakeExecContext, tmp_path)
    original = ctx.snapshot()
    res = DataOpsExecutor().apply(Operation(type=type_, target=SheetRangeTarget(range=ctx.rng(0, 0, 2, 3)), params=params), ctx)
    assert res.status == "ok" and res.output is not None
    assert ctx.snapshot() == original and ctx.writes == 0  # the sheet, formula included, is untouched


def test_the_parameter_is_in_the_form_schema_of_every_in_place_operation() -> None:
    by_type = {d.type: d for d in DataOpsExecutor().describe_all()}
    for type_, _ in IN_PLACE:
        node = by_type[type_].params_schema["properties"]["formulas"]
        assert node["enum"] == ["refuse", "convert_to_values"] and node["default"] == "refuse"
        assert node["title"] == f"ops.{type_}.params.formulas.title"
    for type_, _ in TABLE_MAKING + [("join", {})]:
        assert "formulas" not in by_type[type_].params_schema["properties"]
