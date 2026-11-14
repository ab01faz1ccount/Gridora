"""fill: fill empty cells down, up, or with a constant. Never changes a non-empty cell."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from ..errors import DataOpsError, pointer
from ..ops_common import coerce_scalar
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv


class FillParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    columns: list[str] = Field(default_factory=list, description="d", json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    mode: Literal["down", "up", "constant"] = "down"
    value: bool | float | str | None = Field(None, json_schema_extra={
        "x-gridora-visible-if": {"property": "mode", "equals": "constant"}})


class FillOp(OperationSpec):
    type = "fill"
    category = "clean"
    destructive = False
    Params = FillParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, FillParams)
        cols = params.columns or list(frame.columns)
        exprs = []
        for c in cols:
            col = pl.col(c)
            if frame.schema[c] == pl.String:  # blank text counts as empty
                col = pl.when(col.str.strip_chars() == "").then(None).otherwise(col)
            if params.mode == "constant":
                v = coerce_scalar(params.value, frame.schema[c], pointer("params", "value"))
                exprs.append(col.fill_null(pl.lit(v, dtype=frame.schema[c])).alias(c))
            else:
                exprs.append(col.fill_null(strategy="forward" if params.mode == "down" else "backward").alias(c))
        if params.mode == "constant" and params.value is None:
            raise DataOpsError("invalid_param", "a constant value is required", path=pointer("params", "value"))
        return OpOutput(frame.with_columns(exprs))
