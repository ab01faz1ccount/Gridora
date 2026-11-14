"""sort: multi-key, stable, Persian-aware (docs/OPERATIONS_CATALOG.md)."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from ..persian.chars import collation_key
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field


class SortKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = column_field()
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] = "last"


class SortParams(ParamsModel):
    has_header: bool = Field(True, description="d", json_schema_extra={"x-gridora-order": 0})
    keys: list[SortKey] = Field(min_length=1, max_length=8, description="d",
                                json_schema_extra={"x-gridora-widget": "sort-keys", "x-gridora-order": 1})
    collation: Literal["persian", "binary"] = Field(
        "persian", json_schema_extra={"x-gridora-persian-option": True, "x-gridora-group": "ops.groups.advanced"})


class SortOp(OperationSpec):
    type = "sort"
    category = "order"
    destructive = False
    Params = SortParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, SortParams)
        sort_exprs, desc, nulls_last = [], [], []
        for i, k in enumerate(params.keys):
            col = pl.col(k.column)
            use_key = params.collation == "persian" and frame.schema[k.column] == pl.String
            sort_exprs.append((collation_key(col) if use_key else col).alias(f"__k{i}"))
            desc.append(k.direction == "desc")
            nulls_last.append(k.nulls == "last")
        out = (frame.with_columns(sort_exprs)
               .sort([f"__k{i}" for i in range(len(sort_exprs))], descending=desc, nulls_last=nulls_last,
                     maintain_order=True)
               .select(frame.columns))
        return OpOutput(out)
