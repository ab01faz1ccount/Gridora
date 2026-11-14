"""group_aggregate: group by columns, aggregate others. Always creates a new table."""
from __future__ import annotations

from typing import Literal, Optional

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from ..analytics import AggSpec, aggregate
from ..errors import pointer, verr
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field


class Aggregation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fn: Literal["sum", "avg", "count", "count_distinct", "min", "max"]
    column: Optional[str] = column_field(default=None)
    name: Optional[str] = Field(None, max_length=200)


class GroupParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    by: list[str] = Field(default_factory=list, max_length=20, json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    aggregations: list[Aggregation] = Field(min_length=1, max_length=50, json_schema_extra={"x-gridora-order": 2})
    sort_groups: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})


class GroupAggregateOp(OperationSpec):
    type = "group_aggregate"
    category = "analyze"
    destructive = False
    creates_table = True
    Params = GroupParams

    def validate_static(self, params: ParamsModel):  # type: ignore[no-untyped-def]
        assert isinstance(params, GroupParams)
        return [verr("invalid_param", pointer("params", "aggregations", i, "column"), f"'{a.fn}' needs a column")
                for i, a in enumerate(params.aggregations) if a.fn != "count" and a.column is None]

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, GroupParams)
        aggs = [AggSpec(a.fn, a.column, a.name) for a in params.aggregations]
        return OpOutput(aggregate(frame, params.by, aggs, sort_groups=params.sort_groups))
