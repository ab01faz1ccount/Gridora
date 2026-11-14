"""merge_columns: join several columns into one text column."""
from __future__ import annotations

import polars as pl
from pydantic import Field

from ..conversions import _expr
from ..errors import pointer
from ..ops_common import unique_name
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv


class MergeParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    columns: list[str] = Field(min_length=2, max_length=50, json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    separator: str = Field(" ", max_length=20)
    skip_empty: bool = True
    output_name: str = Field("merged", min_length=1, max_length=200)
    keep_sources: bool = True


class MergeColumnsOp(OperationSpec):
    type = "merge_columns"
    category = "reshape"
    destructive = False
    Params = MergeParams

    def validate_static(self, params: ParamsModel):  # type: ignore[no-untyped-def]
        from ..errors import verr
        assert isinstance(params, MergeParams)
        if len(set(params.columns)) != len(params.columns):
            return [verr("invalid_param", pointer("params", "columns"), "a column is listed twice")]
        return []

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, MergeParams)
        parts = []
        for c in params.columns:
            e = _expr(pl.col(c), frame.schema[c], "string", ".", None) if frame.schema[c] != pl.String else pl.col(c)
            parts.append(pl.when(e.str.strip_chars() == "").then(None).otherwise(e) if params.skip_empty else e)
        if params.skip_empty:
            merged = pl.concat_str(parts, separator=params.separator, ignore_nulls=True)
        else:
            merged = pl.concat_str([p.fill_null("") for p in parts], separator=params.separator)
        merged = pl.when(merged == "").then(None).otherwise(merged)
        name = unique_name(params.output_name, set(frame.columns) - (set() if params.keep_sources else set(params.columns)))
        cols = list(frame.columns)
        last = max(cols.index(c) for c in params.columns)
        out = frame.with_columns(merged.alias(name))
        if params.keep_sources:
            order = cols[:last + 1] + [name] + cols[last + 1:]
        else:
            first = min(cols.index(c) for c in params.columns)
            order = [c for c in cols[:first] if c not in params.columns] + [name] \
                + [c for c in cols[first:] if c not in params.columns]
        return OpOutput(out.select(order))
