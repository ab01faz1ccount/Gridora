"""Aggregation kernel shared by group_aggregate and chart data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import polars as pl

from .errors import DataOpsError
from .ops_common import unique_name
from .persian.chars import collation_key, variant_fold

AGG_FNS = ("sum", "avg", "count", "count_distinct", "min", "max", "median")
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
    if fn in ("sum", "avg", "median") and not dtype.is_numeric():
        raise DataOpsError("type_mismatch", f"'{fn}' needs a numeric column, '{column}' is {dtype}", path=f"{ptr}/column")
    if fn in ("min", "max") and dtype == pl.Boolean:
        raise DataOpsError("type_mismatch", f"'{fn}' is not valid for a yes/no column", path=f"{ptr}/column")
    match fn:
        case "sum":
            return col.sum()
        case "avg":
            return col.mean()
        case "median":
            return col.median()
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
              ignore_variants: bool = False, ptr: str = "/params/aggregations") -> pl.DataFrame:
    """Groups appear in first-appearance order (deterministic) unless `sort_groups` (Persian-aware, stable).
    With `ignore_variants`, text keys that only differ by Arabic/Persian letter variants, ZWNJ, tatweel or
    diacritics fall into ONE group, shown with the spelling of its first row."""
    taken = set(by)
    exprs = []
    for i, a in enumerate(aggs):
        dtype = frame.schema[a.column] if a.column else None
        base = a.name or (f"{a.fn}_{a.column}" if a.column else "count")
        name = unique_name(base, taken)
        taken.add(name)
        exprs.append(agg_expr(a.fn, a.column, dtype, f"{ptr}/{i}").alias(name))
    if by:
        folded = [c for c in by if ignore_variants and frame.schema[c] == pl.String]
        if folded:
            tmp = {c: f"__g{i}" for i, c in enumerate(folded)}
            keys = [pl.col(tmp[c]) if c in tmp else pl.col(c) for c in by]
            out = (frame.with_columns([variant_fold(pl.col(c)).alias(t) for c, t in tmp.items()])
                   .group_by(keys, maintain_order=True)
                   .agg([pl.col(c).first() for c in tmp] + exprs)
                   .drop(list(tmp.values())).select([*by, *[e.meta.output_name() for e in exprs]]))
        else:
            out = frame.group_by(by, maintain_order=True).agg(exprs)
        if sort_groups:
            keys = [(collation_key(pl.col(c)) if frame.schema[c] == pl.String else pl.col(c)).alias(f"__k{i}")
                    for i, c in enumerate(by)]
            out = out.with_columns(keys).sort([f"__k{i}" for i in range(len(by))], nulls_last=True,
                                              maintain_order=True).drop([f"__k{i}" for i in range(len(by))])
        return out
    return frame.select(exprs)
