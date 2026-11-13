"""change_type: convert a column to another type (Persian-digit aware). Destructive: lossy conversions are possible."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from ..conversions import convert_column
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field


class ChangeTypeParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    column: str = column_field()
    to: Literal["int64", "float64", "bool", "string", "date", "datetime", "decimal"]
    on_error: Literal["fail", "null"] = "fail"
    decimal_separator: Literal["dot", "comma"] = Field("dot", json_schema_extra={"x-gridora-group": "ops.groups.advanced"})
    date_format: str | None = Field(None, json_schema_extra={"x-gridora-group": "ops.groups.advanced"})


class ChangeTypeOp(OperationSpec):
    type = "change_type"
    category = "clean"
    destructive = True
    Params = ChangeTypeParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, ChangeTypeParams)
        c = convert_column(frame, params.column, params.to, on_error=params.on_error,
                           decimal_separator="," if params.decimal_separator == "comma" else ".", date_format=params.date_format)
        return OpOutput(c.frame, c.warnings)
