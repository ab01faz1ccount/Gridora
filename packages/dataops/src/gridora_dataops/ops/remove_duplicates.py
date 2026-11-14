"""remove_duplicates: by chosen columns (all columns when none chosen), keep first or last."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from ..persian.chars import variant_fold
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv


class DedupeParams(ParamsModel):
    has_header: bool = Field(True, description="d", json_schema_extra={"x-gridora-order": 0})
    columns: list[str] = Field(default_factory=list, description="d", json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    keep: Literal["first", "last"] = "first"
    case_sensitive: bool = False
    ignore_variants: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})


class RemoveDuplicatesOp(OperationSpec):
    type = "remove_duplicates"
    category = "clean"
    destructive = True  # rows disappear: the API asks for confirmation
    Params = DedupeParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, DedupeParams)
        cols = params.columns or list(frame.columns)
        keys = []
        for i, c in enumerate(cols):
            e = pl.col(c)
            if frame.schema[c] == pl.String:
                if params.ignore_variants:
                    e = variant_fold(e)
                if not params.case_sensitive:
                    e = e.str.to_lowercase()
            keys.append(e.alias(f"__d{i}"))
        names = [f"__d{i}" for i in range(len(keys))]
        out = (frame.with_columns(keys).unique(subset=names, keep=params.keep, maintain_order=True)
               .select(frame.columns))
        return OpOutput(out)
