"""One adapter per chart type. Each decides what its chart needs from the table and says so with typed errors;
the building blocks (common.py, transform.py) are shared, the data shape is not."""
from __future__ import annotations

from collections.abc import Callable
from typing import Optional

import polars as pl
from gridora_contracts.models import ChartData, ChartSeries, ChartSort, ChartSpec

from ..errors import DataOpsError, pointer
from .common import (
    COUNT_LIKE,
    MAX_CATEGORIES,
    MAX_SCATTER_POINTS,
    MAX_SERIES,
    OTHER_CATEGORY,
    Axis,
    Cat,
    Notes,
    aggregate_values,
    category_values,
    need_numeric,
    numbers,
    resolve,
    time_axis,
)
from .distribution import build_boxplot, build_histogram
from .transform import apply_limit, apply_order, order_axis

Values = list[list[Optional[float]]]


def _too_many(count: int, ptr: str) -> DataOpsError:
    return DataOpsError("chart_too_many_categories", f"{count} categories (limit {MAX_CATEGORIES})", path=ptr,
                        hint="use Top N, a filter, or a coarser time step")


def _series_cols(spec: ChartSpec, frame: pl.DataFrame, i: int, s: ChartSeries) -> tuple[str, Optional[str]]:
    vcol = resolve(frame, s.value_col, pointer("series", i, "value_col"))
    ccol = resolve(frame, s.category_col, pointer("series", i, "category_col")) if s.category_col is not None else None
    if s.aggregate not in COUNT_LIKE:
        need_numeric(frame, vcol, pointer("series", i, "value_col"), "series values")
    return vcol, ccol


def _axis_of(frame: pl.DataFrame, ccol: Optional[str], labels_by_iso: Optional[dict[str, str]], cats: list[Cat]) -> Axis:
    if ccol is None:
        return Axis(cats, "number")
    if labels_by_iso is not None:
        return Axis(cats, "time", [labels_by_iso.get(str(c), str(c)) for c in cats])
    return Axis(cats, "number" if frame.schema[ccol].is_numeric() else "category")


def _apply_nulls(values: Values, spec: ChartSpec, notes: Notes) -> Values:
    empty = sum(1 for s in values for v in s if v is None)
    if spec.options.nulls == "zero":
        return [[0.0 if v is None else v for v in s] for s in values]
    if empty:
        notes.add("empty_values", count=empty)
    return values


def _finish(spec: ChartSpec, axis: Axis, names: list[str], values: Values, notes: Notes, *, additive: bool) -> ChartData:
    if spec.limit is not None:
        axis, values = apply_limit(axis, values, spec.limit, additive, notes, keep_order=spec.sort is not None
                                   and spec.sort.by == "source" and not spec.sort.order)
    if spec.sort is not None:
        order = order_axis(axis, values, spec.sort)
        if spec.limit is not None and spec.limit.other and OTHER_CATEGORY in axis.cats:  # "Other" always comes last
            at = axis.cats.index(OTHER_CATEGORY)
            order = [i for i in order if i != at] + [at]
        axis, values = apply_order(axis, values, order)
    elif axis.kind == "time":  # a time axis is always chronological
        axis, values = apply_order(axis, values, order_axis(axis, values, _CHRONO))
    if len(axis.cats) > MAX_CATEGORIES:
        raise _too_many(len(axis.cats), pointer("series", 0, "category_col"))
    values = _apply_nulls(values, spec, notes)
    return ChartData(categories=axis.cats, series=[{"name": n, "values": v} for n, v in zip(names, values, strict=True)],
                     categories_kind=axis.kind, labels=axis.labels, notes=notes.items)


_CHRONO = ChartSort(by="category", direction="asc")


# ------------------------------------------------------------- bar / line / area
def build_cartesian(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    notes = Notes()
    if spec.series_by is not None:
        return _by_group(spec, frame, notes)
    axis: Optional[Axis] = None
    names: list[str] = []
    values: Values = []
    for i, s in enumerate(spec.series):
        vcol, ccol = _series_cols(spec, frame, i, s)
        work, labels_by_iso = (time_axis(frame, ccol, spec.time, notes, pointer("series", i, "category_col"))
                               if ccol else (frame, None))
        if s.aggregate is not None:
            if ccol is None:
                raise DataOpsError("invalid_param", "an aggregate needs a category column", path=pointer("series", i, "aggregate"))
            agg = aggregate_values(work, [ccol], s.aggregate, vcol, f"/series/{i}")
            cats, vals = category_values(agg[ccol]), numbers(agg["__v"])
        else:
            cats = category_values(work[ccol]) if ccol else [float(n) for n in range(1, work.height + 1)]
            vals = numbers(work[vcol])
        if len(cats) > MAX_CATEGORIES and spec.limit is None:
            raise _too_many(len(cats), pointer("series", i, "category_col"))
        this = _axis_of(work, ccol, labels_by_iso, cats)
        if axis is None:
            axis = this
        elif this.cats != axis.cats:
            raise DataOpsError("chart_series_mismatch", "series must share the same categories",
                               path=pointer("series", i, "category_col"))
        names.append(s.name or vcol)
        values.append(vals)
    assert axis is not None
    additive = all(s.aggregate in ("sum", "count") for s in spec.series)
    return _finish(spec, axis, names, values, notes, additive=additive)


def _by_group(spec: ChartSpec, frame: pl.DataFrame, notes: Notes) -> ChartData:
    """One series per value of `series_by` (long-format data). Categories are shared by construction."""
    if len(spec.series) != 1:
        raise DataOpsError("invalid_param", "split by column needs exactly one value column", path=pointer("series_by"))
    s = spec.series[0]
    vcol, ccol = _series_cols(spec, frame, 0, s)
    gcol = resolve(frame, spec.series_by, pointer("series_by"))  # type: ignore[arg-type]
    if ccol is None or s.aggregate is None:
        raise DataOpsError("invalid_param", "split by column needs a category column and an aggregate",
                           path=pointer("series", 0, "aggregate" if ccol else "category_col"))
    work, labels_by_iso = time_axis(frame, ccol, spec.time, notes, pointer("series", 0, "category_col"))
    agg = aggregate_values(work, [ccol, gcol], s.aggregate, vcol, "/series/0")
    cats = list(dict.fromkeys(category_values(agg[ccol])))
    groups = list(dict.fromkeys(category_values(agg[gcol])))
    if len(groups) > MAX_SERIES:
        raise DataOpsError("chart_too_many_series", f"{len(groups)} series (limit {MAX_SERIES})", path=pointer("series_by"))
    pos = {(str(c)): i for i, c in enumerate(cats)}
    table: dict[str, list[Optional[float]]] = {str(g): [None] * len(cats) for g in groups}
    for c, g, v in zip(category_values(agg[ccol]), category_values(agg[gcol]), numbers(agg["__v"]), strict=True):
        table[str(g)][pos[str(c)]] = v
    if len(cats) > MAX_CATEGORIES and spec.limit is None:
        raise _too_many(len(cats), pointer("series", 0, "category_col"))
    axis = _axis_of(work, ccol, labels_by_iso, cats)
    return _finish(spec, axis, [str(g) if not isinstance(g, float) else f"{g:g}" for g in groups],
                   [table[str(g)] for g in groups], notes, additive=s.aggregate in ("sum", "count"))


# ------------------------------------------------------------------------- pie
def build_pie(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    """One series of parts of a whole: negative and empty values cannot be drawn, so they are left out and counted."""
    notes = Notes()
    if len(spec.series) > 1:
        notes.add("extra_series_ignored", count=len(spec.series) - 1)
    s = spec.series[0]
    vcol, ccol = _series_cols(spec, frame, 0, s)
    if ccol is None:
        raise DataOpsError("invalid_param", "a pie chart needs a category column", path=pointer("series", 0, "category_col"))
    if spec.series_by is not None:
        raise DataOpsError("invalid_param", "a pie chart has one series", path=pointer("series_by"))
    if s.aggregate is not None:
        agg = aggregate_values(frame, [ccol], s.aggregate, vcol, "/series/0")
        cats, vals = category_values(agg[ccol]), numbers(agg["__v"])
    else:
        cats, vals = category_values(frame[ccol]), numbers(frame[vcol])
    keep = [i for i, v in enumerate(vals) if v is not None and v >= 0]
    neg = sum(1 for v in vals if v is not None and v < 0)
    empty = sum(1 for v in vals if v is None)
    if neg:
        notes.add("negative_values", count=neg)
    if empty:
        notes.add("empty_values", count=empty)
    if not keep or all(vals[i] == 0 for i in keep):
        raise DataOpsError("invalid_param", "a pie chart needs at least one positive value", path=pointer("series", 0, "value_col"),
                           hint="check the value column, or use a bar chart for values that can be negative")
    axis = Axis([cats[i] for i in keep])
    return _finish(spec, axis, [s.name or vcol], [[vals[i] for i in keep]], notes, additive=s.aggregate in ("sum", "count"))


# --------------------------------------------------------------------- scatter
def build_scatter(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    """Row-level points: nothing is aggregated. A point needs both x and y; others are left out and counted."""
    notes = Notes()
    cols: list[tuple[str, str]] = []
    for i, s in enumerate(spec.series):
        vcol, ccol = _series_cols(spec, frame, i, s)
        if ccol is None or not frame.schema[ccol].is_numeric():
            raise DataOpsError("type_mismatch", "a scatter chart needs a numeric x column (category_col)",
                               path=pointer("series", i, "category_col"))
        if s.aggregate is not None:
            raise DataOpsError("invalid_param", "a scatter chart shows rows as they are (no aggregate)",
                               path=pointer("series", i, "aggregate"))
        cols.append((ccol, vcol))
    xcol = cols[0][0]
    if any(c[0] != xcol for c in cols):
        raise DataOpsError("chart_series_mismatch", "series must share the same categories", path=pointer("series", 1, "category_col"))
    gcol = resolve(frame, spec.series_by, pointer("series_by")) if spec.series_by is not None else None
    if gcol is not None and len(spec.series) != 1:
        raise DataOpsError("invalid_param", "split by column needs exactly one value column", path=pointer("series_by"))
    ycols = [c[1] for c in cols]
    xs = numbers(frame[xcol])
    ys = [numbers(frame[c]) for c in ycols]
    keep = [r for r in range(frame.height) if xs[r] is not None and any(y[r] is not None for y in ys)]
    if frame.height - len(keep):
        notes.add("rows_excluded", count=frame.height - len(keep), reason="empty_value")
    if len(keep) > MAX_SCATTER_POINTS:  # deterministic: every k-th kept row, always including the first
        step = -(-len(keep) // MAX_SCATTER_POINTS)
        notes.add("sampled", kept=len(keep[::step]), total=len(keep))
        keep = keep[::step]
    cats: list[Cat] = [float(xs[r]) for r in keep]  # type: ignore[arg-type]
    if gcol is None:
        names = [s.name or c for s, c in zip(spec.series, ycols, strict=True)]
        values: Values = [[y[r] for r in keep] for y in ys]
    else:
        gvals = category_values(frame[gcol])
        groups = list(dict.fromkeys(str(gvals[r]) for r in keep))
        if len(groups) > MAX_SERIES:
            raise DataOpsError("chart_too_many_series", f"{len(groups)} series (limit {MAX_SERIES})", path=pointer("series_by"))
        names = groups
        values = [[ys[0][r] if str(gvals[r]) == g else None for r in keep] for g in groups]
    return ChartData(categories=cats, series=[{"name": n, "values": v} for n, v in zip(names, values, strict=True)],
                     categories_kind="number", notes=notes.items)


ADAPTERS: dict[str, Callable[[ChartSpec, pl.DataFrame], ChartData]] = {
    "bar": build_cartesian, "line": build_cartesian, "area": build_cartesian, "pie": build_pie, "scatter": build_scatter,
    "histogram": build_histogram, "boxplot": build_boxplot,
}
