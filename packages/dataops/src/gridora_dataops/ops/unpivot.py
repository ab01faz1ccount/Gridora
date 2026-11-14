"""unpivot: wide to long."""
from __future__ import annotations

import polars as pl
from gridora_contracts.models import Warning_
from pydantic import Field

from ..conversions import _expr
from ..errors import DataOpsError, pointer
from ..ops_common import unique_name
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv


class UnpivotParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    id_columns: list[str] = Field(default_factory=list, max_length=50, json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    value_columns: list[str] = Field(default_factory=list, max_length=500, description="d", json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 2})
    variable_name: str = Field("variable", min_length=1, max_length=200)
    value_name: str = Field("value", min_length=1, max_length=200)


class UnpivotOp(OperationSpec):
    type = "unpivot"
    category = "analyze"
    destructive = False
    creates_table = True
    Params = UnpivotParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, UnpivotParams)
        ids = params.id_columns
        values = params.value_columns or [c for c in frame.columns if c not in ids]
        if set(values) & set(ids):
            raise DataOpsError("invalid_param", "a column cannot be both id and value",
                               path=pointer("params", "value_columns"))
        if not values:
            raise DataOpsError("invalid_param", "no value columns to unpivot", path=pointer("params", "value_columns"))
        warnings: list[Warning_] = []
        kinds = {frame.schema[c] for c in values}
        work = frame
        if len(kinds) > 1 and not all(frame.schema[c].is_numeric() for c in values):
            work = frame.with_columns([_expr(pl.col(c), frame.schema[c], "string", ".", None).alias(c)
                                       if frame.schema[c] != pl.String else pl.col(c) for c in values])
            warnings.append(Warning_(code="unpivot_values_as_text", severity="warn",
                                     message="value columns have different types; all values were converted to text"))
        taken = set(ids)
        var = unique_name(params.variable_name, taken)
        val = unique_name(params.value_name, taken | {var})
        return OpOutput(work.unpivot(on=values, index=ids or None, variable_name=var, value_name=val), warnings)
