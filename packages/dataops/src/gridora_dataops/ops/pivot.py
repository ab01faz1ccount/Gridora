"""pivot: rows = index columns, new columns = distinct values of one column, cells = an aggregate."""
from __future__ import annotations

from typing import Literal, Optional

import polars as pl
from pydantic import Field

from ..analytics import NULL_CATEGORY
from ..errors import DataOpsError, pointer
from ..ops_common import unique_name
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field

MAX_PIVOT_COLUMNS = 200
_FN: dict[str, Literal["sum", "mean", "len", "min", "max", "first"]] = {
    "sum": "sum", "avg": "mean", "count": "len", "min": "min", "max": "max", "first": "first"}


class PivotParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    index: list[str] = Field(min_length=1, max_length=20, json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    columns: str = column_field()
    values: str = column_field()
    fn: Literal["sum", "avg", "count", "min", "max", "first"] = "sum"
    fill_value: Optional[float] = None


class PivotOp(OperationSpec):
    type = "pivot"
    category = "analyze"
    destructive = False
    creates_table = True
    rewrites_cells = False  # reads the range, never changes it: formulas are fine (their values are used)
    Params = PivotParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, PivotParams)
        vdtype = frame.schema[params.values]
        if params.fn in ("sum", "avg") and not vdtype.is_numeric():
            raise DataOpsError("type_mismatch", f"'{params.fn}' needs a numeric values column",
                               path=pointer("params", "values"))
        if params.columns in params.index or params.values in params.index or params.columns == params.values:
            raise DataOpsError("invalid_param", "index, columns and values must be different columns",
                               path=pointer("params", "columns"))
        piv = pl.col(params.columns).cast(pl.String).fill_null(NULL_CATEGORY)
        # index columns get private names while pivoting: a pivoted value called like an index column ("r") used to
        # crash the run with an untyped duplicate-column error
        ix = [f"__ix{i}" for i in range(len(params.index))]
        work = frame.select([*[pl.col(c).alias(t) for c, t in zip(params.index, ix, strict=True)],
                             piv.alias(params.columns), pl.col(params.values)])
        n = work[params.columns].n_unique()
        if n > MAX_PIVOT_COLUMNS:
            raise DataOpsError("result_too_large", f"{n} distinct values would create too many columns "
                               f"(limit {MAX_PIVOT_COLUMNS})", path=pointer("params", "columns"))
        out = work.pivot(on=params.columns, index=ix, values=params.values,
                         aggregate_function=_FN[params.fn], maintain_order=True, sort_columns=False)
        if params.fn == "sum":  # Polars gives 0 for a missing combination; an empty cell says "no data", 0 says "zero"
            seen = work.pivot(on=params.columns, index=ix, values=params.values, aggregate_function="len",
                              maintain_order=True, sort_columns=False)
            out = out.with_columns([pl.when(seen[c] == 0).then(None).otherwise(out[c]).alias(c)
                                    for c in out.columns if c not in ix])
        taken = set(params.index)
        renames = {}
        for c in out.columns:
            if c in ix:
                continue
            new = unique_name(c, taken)
            taken.add(new)
            if new != c:
                renames[c] = new
        out = out.rename({**renames, **dict(zip(ix, params.index, strict=True))})
        if params.fill_value is not None:
            out = out.with_columns([pl.col(c).fill_null(params.fill_value) for c in out.columns if c not in params.index])
        return OpOutput(out)
