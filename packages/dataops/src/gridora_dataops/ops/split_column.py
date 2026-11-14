"""split_column: split one text column into several by a delimiter or fixed widths."""
from __future__ import annotations

import re
from typing import Literal

import polars as pl
from pydantic import Field

from ..errors import DataOpsError, pointer
from ..ops_common import unique_name
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field

MAX_PARTS = 50


class SplitParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    column: str = column_field(types=["text"])
    mode: Literal["delimiter", "fixed_width"] = "delimiter"
    delimiter: str = Field(",", max_length=20, json_schema_extra={
        "x-gridora-visible-if": {"property": "mode", "equals": "delimiter"}})
    merge_delimiters: bool = Field(False, json_schema_extra={
        "x-gridora-visible-if": {"property": "mode", "equals": "delimiter"}})
    max_parts: int | None = Field(None, ge=2, le=MAX_PARTS, json_schema_extra={
        "x-gridora-visible-if": {"property": "mode", "equals": "delimiter"}})
    widths: list[int] = Field(default_factory=list, max_length=MAX_PARTS, json_schema_extra={
        "x-gridora-visible-if": {"property": "mode", "equals": "fixed_width"}})
    trim_parts: bool = True
    keep_source: bool = False


class SplitColumnOp(OperationSpec):
    type = "split_column"
    category = "reshape"
    destructive = True
    Params = SplitParams

    def validate_static(self, params: ParamsModel):  # type: ignore[no-untyped-def]
        from ..errors import verr
        assert isinstance(params, SplitParams)
        if params.mode == "delimiter" and not params.delimiter:
            return [verr("invalid_param", pointer("params", "delimiter"), "the delimiter must not be empty")]
        if params.mode == "fixed_width" and (not params.widths or any(w < 1 for w in params.widths)):
            return [verr("invalid_param", pointer("params", "widths"), "give one or more positive widths")]
        return []

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, SplitParams)
        if frame.schema[params.column] != pl.String:
            raise DataOpsError("type_mismatch", f"column '{params.column}' is not text",
                               path=pointer("params", "column"))
        col = pl.col(params.column)
        if params.mode == "delimiter":
            src = col
            if params.merge_delimiters:
                src = src.str.replace_all(f"(?:{re.escape(params.delimiter)})+", params.delimiter, literal=False)
            parts = src.str.split(params.delimiter)
            n = frame.select(parts.list.len().max()).item() or 1
            n = min(n, params.max_parts or MAX_PARTS)
            if n > MAX_PARTS:
                raise DataOpsError("invalid_param", f"more than {MAX_PARTS} parts", path=pointer("params", "delimiter"))
            exprs = [parts.list.get(i, null_on_oob=True) for i in range(n)]
            if params.max_parts and n == params.max_parts:  # the last part keeps the rest of the text
                exprs[-1] = parts.list.slice(n - 1).list.join(params.delimiter)
                exprs[-1] = pl.when(parts.list.len() >= n).then(exprs[-1])
        else:
            exprs, offset = [], 0
            for w in params.widths:
                exprs.append(col.str.slice(offset, w))
                offset += w
        taken = set(frame.columns) - ({params.column} if not params.keep_source else set())
        names: list[str] = []
        for i in range(len(exprs)):
            name = unique_name(f"{params.column}_{i + 1}", taken | set(names))
            names.append(name)
        new = []
        for name, e in zip(names, exprs, strict=True):
            if params.trim_parts:
                e = e.str.strip_chars()
            new.append(pl.when(e == "").then(None).otherwise(e).alias(name))
        out = frame.with_columns(new)
        i = list(frame.columns).index(params.column)
        if params.keep_source:
            order = list(frame.columns[:i + 1]) + names + list(frame.columns[i + 1:])
        else:
            order = list(frame.columns[:i]) + names + list(frame.columns[i + 1:])
        return OpOutput(out.select(order))
