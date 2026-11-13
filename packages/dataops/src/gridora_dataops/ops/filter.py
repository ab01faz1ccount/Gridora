"""filter: condition tree (and/or groups) over text, number, date and empty tests.

On a data table the result stays in the table (new version, M2). On a sheet range the result goes to a NEW table
(Phase 2 decision A2-Q2) so the source rows are never lost; that path needs the TableStore (M2). Preview works
for both today.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, ClassVar, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from ..errors import DataOpsError, pointer
from ..persian.chars import variant_fold
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field

Op = Literal["eq", "ne", "gt", "ge", "lt", "le", "between", "contains", "not_contains",
             "starts_with", "ends_with", "is_empty", "is_not_empty"]
TEXT_OPS = {"contains", "not_contains", "starts_with", "ends_with"}
ORDER_OPS = {"gt", "ge", "lt", "le", "between"}
Scalar = bool | float | str


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["condition"] = "condition"
    column: str = column_field()
    op: Op
    value: Scalar | None = None
    value2: Scalar | None = None
    case_sensitive: bool = False
    ignore_variants: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["group"] = "group"
    logic: Literal["and", "or"] = "and"
    items: list[Annotated[Condition | Group, Field(discriminator="kind")]] = Field(min_length=1, max_length=50)


Group.model_rebuild()


class FilterParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    where: Annotated[Condition | Group, Field(discriminator="kind")] = Field(
        json_schema_extra={"x-gridora-widget": "condition-builder", "x-gridora-order": 1})


def _fold(e: pl.Expr, c: Condition) -> pl.Expr:
    if c.ignore_variants:
        e = variant_fold(e)
    return e if c.case_sensitive else e.str.to_lowercase()


def _scalar(c: Condition, dtype: pl.DataType, which: str, value: Scalar | None, ptr: str) -> Any:
    if value is None:
        raise DataOpsError("invalid_param", f"'{c.op}' needs a value", path=ptr + pointer(which))
    try:
        if dtype.is_temporal():
            if not isinstance(value, str):
                raise ValueError
            d = dt.datetime.fromisoformat(value) if len(value) > 10 else dt.date.fromisoformat(value)
            return d if dtype == pl.Datetime("us") or isinstance(dtype, pl.Datetime) else (
                d.date() if isinstance(d, dt.datetime) else d)
        if dtype.is_numeric():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError
            return float(value)
        if dtype == pl.Boolean:
            if not isinstance(value, bool):
                raise ValueError
            return value
        if dtype == pl.String:
            if not isinstance(value, str):
                raise ValueError
            return value
    except ValueError:
        pass
    raise DataOpsError("type_mismatch", f"value is not valid for a {dtype} column", path=ptr + pointer(which))


def _condition(c: Condition, schema: pl.Schema, ptr: str) -> pl.Expr:
    dtype = schema[c.column]
    col = pl.col(c.column)
    if c.op in ("is_empty", "is_not_empty"):
        empty = col.is_null()
        if dtype == pl.String:
            empty = empty | (col.str.strip_chars() == "")
        return empty if c.op == "is_empty" else ~empty
    if c.op in TEXT_OPS and dtype != pl.String:
        raise DataOpsError("type_mismatch", f"'{c.op}' needs a text column", path=ptr + pointer("op"))
    if c.op in ORDER_OPS and dtype == pl.Boolean:
        raise DataOpsError("type_mismatch", f"'{c.op}' is not valid for a yes/no column", path=ptr + pointer("op"))
    v = _scalar(c, dtype, "value", c.value, ptr)
    if dtype == pl.String:
        left, right = _fold(col, c), _fold(pl.lit(v), c)
    else:
        left, right = col, pl.lit(v)
    null_means = c.op in ("ne", "not_contains")  # blanks are included in "not equal" / "does not contain"
    match c.op:
        case "eq":
            r = left == right
        case "ne":
            r = left != right
        case "gt":
            r = left > right
        case "ge":
            r = left >= right
        case "lt":
            r = left < right
        case "le":
            r = left <= right
        case "between":
            hi = _scalar(c, dtype, "value2", c.value2, ptr)
            r = (left >= right) & (left <= (_fold(pl.lit(hi), c) if dtype == pl.String else pl.lit(hi)))
        case "contains":
            r = left.str.contains(right, literal=True)
        case "not_contains":
            r = ~left.str.contains(right, literal=True)
        case "starts_with":
            r = left.str.starts_with(right)
        case "ends_with":
            r = left.str.ends_with(right)
        case _:  # pragma: no cover - guarded by the Literal type
            raise DataOpsError("invalid_param", "unknown operator", path=ptr + pointer("op"))
    return r.fill_null(null_means)


def _node(n: Condition | Group, schema: pl.Schema, ptr: str) -> pl.Expr:
    if isinstance(n, Condition):
        return _condition(n, schema, ptr)
    parts = [_node(item, schema, ptr + pointer("items", i)) for i, item in enumerate(n.items)]
    out = parts[0]
    for p in parts[1:]:
        out = (out & p) if n.logic == "and" else (out | p)
    return out


class FilterOp(OperationSpec):
    type = "filter"
    category = "select"
    destructive = False
    Params = FilterParams
    sheet_output: ClassVar[str] = "new_table"

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, FilterParams)
        return OpOutput(frame.filter(_node(params.where, frame.schema, pointer("params", "where"))))
