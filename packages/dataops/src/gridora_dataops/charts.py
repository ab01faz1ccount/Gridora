"""Chart data: ChartSpec + a frame -> plain categories and series (ChartData)."""
from __future__ import annotations

import math
from typing import Any, Union

import polars as pl
from gridora_contracts.models import ChartData, ChartSpec

from .analytics import NULL_CATEGORY, AggSpec, aggregate
from .errors import DataOpsError, pointer

MAX_CATEGORIES = 5000


def _resolve(frame: pl.DataFrame, ref: Union[str, int], ptr: str) -> str:
    if isinstance(ref, int):
        if not 0 <= ref < frame.width:
            raise DataOpsError("unknown_column", f"column index {ref} is out of range", path=ptr)
        return frame.columns[ref]
    if ref not in frame.columns:
        raise DataOpsError("unknown_column", f"column '{ref}' does not exist", path=ptr)
    return ref


def _category_values(s: pl.Series) -> list[Union[str, float]]:
    out: list[Union[str, float]] = []
    for v in s.to_list():
        if v is None:
            out.append(NULL_CATEGORY)
        elif isinstance(v, bool):
            out.append("true" if v else "false")
        elif isinstance(v, (int, float)):
            out.append(float(v))
        elif hasattr(v, "isoformat"):
            out.append(v.isoformat())
        else:
            out.append(str(v))
    return out


def _numbers(s: pl.Series) -> list[Any]:
    return [None if v is None or (isinstance(v, float) and not math.isfinite(v)) else float(v) for v in s.to_list()]


def build_chart_data(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    if not spec.series:
        raise DataOpsError("invalid_param", "a chart needs at least one series", path=pointer("series"))
    categories: Union[list[Union[str, float]], None] = None
    series_out: list[dict[str, Any]] = []
    for i, s in enumerate(spec.series):
        vcol = _resolve(frame, s.value_col, pointer("series", i, "value_col"))
        ccol = _resolve(frame, s.category_col, pointer("series", i, "category_col")) if s.category_col is not None else None
        if s.aggregate != "count" and not frame.schema[vcol].is_numeric():
            raise DataOpsError("type_mismatch", f"series values '{vcol}' must be numeric",
                               path=pointer("series", i, "value_col"))
        if spec.type == "scatter" and (ccol is None or not frame.schema[ccol].is_numeric()):
            raise DataOpsError("type_mismatch", "a scatter chart needs a numeric x column (category_col)",
                               path=pointer("series", i, "category_col"))
        if s.aggregate is not None:
            if ccol is None:
                raise DataOpsError("invalid_param", "an aggregate needs a category column",
                                   path=pointer("series", i, "aggregate"))
            agg = aggregate(frame, [ccol], [AggSpec(s.aggregate if s.aggregate != "count" else "count", vcol, "__v")],
                            ptr=f"/series/{i}")
            cats, vals = _category_values(agg[ccol]), _numbers(agg["__v"])
        else:
            cats = _category_values(frame[ccol]) if ccol else [float(n) for n in range(1, frame.height + 1)]
            vals = _numbers(frame[vcol])
        if len(cats) > MAX_CATEGORIES:
            raise DataOpsError("chart_too_many_categories", f"{len(cats)} categories (limit {MAX_CATEGORIES})",
                               path=pointer("series", i, "category_col"))
        if categories is None:
            categories = cats
        elif cats != categories:
            raise DataOpsError("chart_series_mismatch", "series must share the same categories",
                               path=pointer("series", i, "category_col"))
        series_out.append({"name": s.name or vcol, "values": vals})
    assert categories is not None
    return ChartData(categories=categories, series=series_out)
