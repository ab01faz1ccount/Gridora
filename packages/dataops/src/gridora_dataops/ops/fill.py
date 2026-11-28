"""fill: fill empty cells down, up, or with a constant. Never changes a non-empty cell."""
from __future__ import annotations

from typing import Literal

import polars as pl
from gridora_contracts.models import Warning_
from pydantic import Field

from ..errors import DataOpsError, pointer
from ..ops_common import coerce_scalar
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, RewriteParams


class FillParams(RewriteParams):
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
        explicit = bool(params.columns)
        cols = params.columns or list(frame.columns)
        if params.mode == "constant" and params.value is None:
            raise DataOpsError("invalid_param", "a constant value is required", path=pointer("params", "value"))
        exprs = []
        skipped: list[str] = []
        for c in cols:
            col = pl.col(c)
            if frame.schema[c] == pl.String:  # blank text counts as empty
                col = pl.when(col.str.strip_chars() == "").then(None).otherwise(col)
            if params.mode == "constant":
                try:
                    v = coerce_scalar(params.value, frame.schema[c], pointer("params", "value"))
                except DataOpsError as e:
                    if explicit:  # the person chose this column: say which one cannot take the value
                        raise DataOpsError(e.code, f"the value does not fit column '{c}' ({frame.schema[c]})",
                                           path=e.errors[0].path, hint="pick a value of the column's type") from None
                    skipped.append(c)  # "all columns": a number is simply not a text column's business
                    continue
                exprs.append(col.fill_null(pl.lit(v, dtype=frame.schema[c])).alias(c))
            else:
                exprs.append(col.fill_null(strategy="forward" if params.mode == "down" else "backward").alias(c))
        if params.mode == "constant" and not exprs:
            raise DataOpsError("type_mismatch", "the value fits none of the columns", path=pointer("params", "value"))
        warns = [Warning_(code="fill_skipped_columns", severity="info", location=", ".join(skipped),
                          message=f"{len(skipped)} column(s) were left as they are: the value does not fit their type")] if skipped else []
        return OpOutput(frame.with_columns(exprs), warns)
