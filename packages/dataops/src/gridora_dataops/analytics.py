"""Aggregation kernel shared by group_aggregate and chart data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import polars as pl

from .errors import DataOpsError
from .ops_common import unique_name
from .persian.chars import collation_key

AGG_FNS = ("sum", "avg", "count", "count_distinct", "min", "max")
NULL_CATEGORY = "(خالی)"


@dataclass
class AggSpec:
    fn: str
    column: Optional[str]
    name: Optional[str] = None


def agg_expr(fn: str, column: Optional[str], dtype: Optional[pl.DataType], ptr: str) -> pl.Expr:
    if column is None:
        if fn != "count":
            raise DataOpsError("invalid_param", f"'{fn}' needs a column", path=f"{ptr}/column")
        return pl.len()
    col = pl.col(column)
    assert dtype is not None
    if fn in ("sum", "avg") and not dtype.is_numeric():
        raise DataOpsError("type_mismatch", f"'{fn}' needs a numeric column, '{column}' is {dtype}", path=f"{ptr}/column")
    if fn in ("min", "max") and dtype == pl.Boolean:
        raise DataOpsError("type_mismatch", f"'{fn}' is not valid for a yes/no column", path=f"{ptr}/column")
    match fn:
        case "sum":
            return col.sum()
        case "avg":
            return col.mean()
        case "min":
            return col.min()
        case "max":
            return col.max()
        case "count":
            return col.count()  # non-empty values
        case "count_distinct":
            return col.drop_nulls().n_unique()
    raise DataOpsError("invalid_param", f"unknown aggregate '{fn}'", path=f"{ptr}/fn")


def aggregate(frame: pl.DataFrame, by: list[str], aggs: list[AggSpec], *, sort_groups: bool = False,
              ptr: str = "/params/aggregations") -> pl.DataFrame:
    """Groups appear in first-appearance order (deterministic) unless `sort_groups` (Persian-aware, stable)."""
    taken = set(by)
    exprs = []
    for i, a in enumerate(aggs):
        dtype = frame.schema[a.column] if a.column else None
        base = a.name or (f"{a.fn}_{a.column}" if a.column else "count")
        name = unique_name(base, taken)
        taken.add(name)
        exprs.append(agg_expr(a.fn, a.column, dtype, f"{ptr}/{i}").alias(name))
    if by:
        out = frame.group_by(by, maintain_order=True).agg(exprs)
        if sort_groups:
            keys = [(collation_key(pl.col(c)) if frame.schema[c] == pl.String else pl.col(c)).alias(f"__k{i}")
                    for i, c in enumerate(by)]
            out = out.with_columns(keys).sort([f"__k{i}" for i in range(len(by))], nulls_last=True,
                                              maintain_order=True).drop([f"__k{i}" for i in range(len(by))])
        return out
    return frame.select(exprs)
