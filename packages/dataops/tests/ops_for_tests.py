"""Test-only operations. Production operations (sort, filter, ...) arrive in M1."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from gridora_dataops.registry import OperationRegistry
from gridora_dataops.spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field


class UpperParams(ParamsModel):
    has_header: bool = True
    column: str = column_field()
    mode: Literal["upper", "lower"] = "upper"
    keys: list[str] = Field(default_factory=list, json_schema_extra={"x-gridora-column": True})
    formulas: Literal["refuse", "convert_to_values"] = "refuse"


class CaseOp(OperationSpec):
    type = "t_case"
    category = "clean"
    destructive = True
    Params = UpperParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, UpperParams)
        col = pl.col(params.column)
        expr = col.str.to_uppercase() if params.mode == "upper" else col.str.to_lowercase()
        return OpOutput(frame.with_columns(expr))


class DropParams(ParamsModel):
    has_header: bool = True
    column: str = column_field()


class DropEmptyOp(OperationSpec):
    """Shrinking operation (like filter/dedupe): removes rows where `column` is empty."""

    type = "t_drop_empty"
    category = "select"
    Params = DropParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, DropParams)
        return OpOutput(frame.filter(pl.col(params.column).is_not_null()))


class WidenOp(OperationSpec):
    """Adds a column (like split_column): needs space to the right."""

    type = "t_widen"
    category = "reshape"
    Params = DropParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        return OpOutput(frame.with_columns(pl.lit("x").alias("extra")))


class BadOp(CaseOp):
    type = "t_bad"

    def validate_static(self, params: ParamsModel):  # type: ignore[no-untyped-def]
        from gridora_dataops.errors import verr
        return [verr("invalid_param", "/params/mode", "static rule failed")]


def build_registry() -> OperationRegistry:
    reg = OperationRegistry()
    for spec in (CaseOp(), DropEmptyOp(), WidenOp(), BadOp()):
        reg.register(spec)
    return reg
