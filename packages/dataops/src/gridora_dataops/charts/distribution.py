"""Distribution charts: histogram (how often values fall in a range) and box plot (spread and outliers).

Both read ONE numeric column, never aggregate rows into sums, and compute their own shape; the renderer only draws
what comes back in `ChartData.meta` (`kind` says which)."""
from __future__ import annotations

import math
from typing import Any, Optional

import polars as pl
from gridora_contracts.models import ChartData, ChartSpec

from ..errors import DataOpsError, pointer
from .common import MAX_CATEGORIES, Axis, Notes, category_values, need_numeric, resolve
from .transform import apply_order, order_axis

MIN_AUTO_BINS = 5
MAX_AUTO_BINS = 50
MAX_BINS = 200
MAX_BOX_GROUPS = 50
MAX_OUTLIERS_PER_GROUP = 300
SMALL_SAMPLE = 5
WHISKER_IQR = 1.5  # Tukey: whiskers reach the furthest value within 1.5 x IQR of the box


def _round(x: float) -> float:
    """Edges and statistics without float noise (0.30000000000000004 -> 0.3)."""
    return float(f"{x:.12g}")


def _one_series(spec: ChartSpec, frame: pl.DataFrame, notes: Notes, *, grouped: bool) -> tuple[str, Optional[str]]:
    if spec.series_by is not None:
        raise DataOpsError("invalid_param", f"a {spec.type} has no series split", path=pointer("series_by"))
    if spec.limit is not None:
        raise DataOpsError("invalid_param", f"Top N does not apply to a {spec.type}", path=pointer("limit"))
    if len(spec.series) > 1:
        notes.add("extra_series_ignored", count=len(spec.series) - 1)
    s = spec.series[0]
    if s.aggregate is not None:
        raise DataOpsError("invalid_param", f"a {spec.type} shows the values as they are (no aggregate)",
                           path=pointer("series", 0, "aggregate"))
    vcol = resolve(frame, s.value_col, pointer("series", 0, "value_col"))
    need_numeric(frame, vcol, pointer("series", 0, "value_col"), "values")
    ccol: Optional[str] = None
    if s.category_col is not None:
        if not grouped:
            raise DataOpsError("invalid_param", "a histogram uses a single column", path=pointer("series", 0, "category_col"),
                               hint="remove the group column, or use a box plot to compare groups")
        ccol = resolve(frame, s.category_col, pointer("series", 0, "category_col"))
    return vcol, ccol


# --------------------------------------------------------------------------- histogram
def _nice_width(raw: float) -> float:
    mag = 10 ** math.floor(math.log10(raw))
    f = raw / mag
    return float((1 if f < 1.5 else 2 if f < 3 else 5 if f < 7 else 10) * mag)


def _auto_width(vals: pl.Series, lo: float, hi: float) -> float:
    """Freedman-Diaconis width (robust to outliers), Sturges when the spread is zero; then a round number, and
    never fewer than 5 or more than 50 bins."""
    n = len(vals)
    q1, q3 = vals.quantile(0.25, "linear"), vals.quantile(0.75, "linear")
    iqr = float(q3) - float(q1) if q1 is not None and q3 is not None else 0.0
    span = hi - lo
    width = 2 * iqr / n ** (1 / 3) if iqr > 0 else span / (math.ceil(math.log2(n)) + 1)
    width = min(max(width, span / MAX_AUTO_BINS), span / MIN_AUTO_BINS)
    return _nice_width(width)


def _edges(spec: ChartSpec, vals: pl.Series) -> list[float]:
    lo, hi = float(vals.min()), float(vals.max())  # type: ignore[arg-type]
    o = spec.options
    if o.bins is not None and o.bin_width is not None:
        raise DataOpsError("invalid_param", "choose the number of bins or their width, not both", path=pointer("options", "bin_width"))
    if lo == hi:  # constant column: one bin around the value
        return [_round(lo - 0.5), _round(lo + 0.5)]
    if o.bins is not None:
        step = (hi - lo) / o.bins
        return [_round(lo + i * step) for i in range(o.bins)] + [_round(hi)]
    width = o.bin_width if o.bin_width is not None else _auto_width(vals, lo, hi)
    start = math.floor(lo / width + 1e-9) * width
    count = max(1, math.ceil((hi - start) / width - 1e-9))
    if count > MAX_BINS:
        raise DataOpsError("invalid_param", f"{count} bins (limit {MAX_BINS})", path=pointer("options", "bin_width"),
                           hint="use a wider bin or fewer bins")
    return [_round(start + i * width) for i in range(count + 1)]


def build_histogram(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    notes = Notes()
    vcol, _ = _one_series(spec, frame, notes, grouped=False)
    raw = frame[vcol].cast(pl.Float64, strict=False)
    vals = raw.filter(raw.is_not_null() & raw.is_finite())
    if len(raw) - len(vals):
        notes.add("rows_excluded", count=len(raw) - len(vals), reason="empty_value")
    name = spec.series[0].name or vcol
    pct = spec.options.as_percent
    if len(vals) == 0:
        return ChartData(categories=[], series=[{"name": name, "values": []}], categories_kind="number", notes=notes.items,
                         meta={"kind": "histogram", "edges": [], "counts": [], "total": 0, "percent": pct})
    edges = _edges(spec, vals)
    n = len(edges) - 1
    # a value belongs to the bin whose left edge is the last one <= value; the maximum closes the last bin
    idx = pl.Series(edges).search_sorted(vals, side="right") - 1
    counts = [0] * n
    for i, c in idx.clip(0, n - 1).value_counts().iter_rows():
        counts[int(i)] = int(c)
    total = len(vals)
    shown = [c / total * 100 for c in counts] if pct else [float(c) for c in counts]
    labels = [f"{edges[i]:g}–{edges[i + 1]:g}" for i in range(n)]
    return ChartData(categories=labels, series=[{"name": name, "values": shown}], categories_kind="category", notes=notes.items,
                     meta={"kind": "histogram", "edges": edges, "counts": counts, "total": total, "percent": pct})


# ---------------------------------------------------------------------------- box plot
def _box(label: str, v: pl.Series, with_outliers: bool, notes_state: dict[str, int]) -> dict[str, Any]:
    n = len(v)
    q1, med, q3 = (float(v.quantile(q, "linear")) for q in (0.25, 0.5, 0.75))  # type: ignore[arg-type]  # same rule as Excel QUARTILE.INC
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - WHISKER_IQR * iqr, q3 + WHISKER_IQR * iqr
    inside = v.filter((v >= lo_fence) & (v <= hi_fence))
    out = v.filter((v < lo_fence) | (v > hi_fence)).sort()
    shown = out.to_list()
    if len(shown) > MAX_OUTLIERS_PER_GROUP:  # keep the most extreme on both sides
        half = MAX_OUTLIERS_PER_GROUP // 2
        notes_state["outliers_total"] += len(shown)
        notes_state["outliers_shown"] += MAX_OUTLIERS_PER_GROUP
        shown = shown[:half] + shown[-half:]
    return {
        "category": label, "n": n, "min": _round(float(v.min())), "q1": _round(q1), "median": _round(med), "q3": _round(q3),  # type: ignore[arg-type]
        "max": _round(float(v.max())),  # type: ignore[arg-type]
        "whisker_low": _round(float(inside.min())), "whisker_high": _round(float(inside.max())),  # type: ignore[arg-type]
        "outliers": [_round(x) for x in shown] if with_outliers else [],
        "outlier_count": len(out),
    }


def build_boxplot(spec: ChartSpec, frame: pl.DataFrame) -> ChartData:
    notes = Notes()
    vcol, ccol = _one_series(spec, frame, notes, grouped=True)
    name = spec.series[0].name or vcol
    raw = frame[vcol].cast(pl.Float64, strict=False)
    keep = raw.is_not_null() & raw.is_finite()
    if len(raw) - int(keep.sum()):
        notes.add("rows_excluded", count=len(raw) - int(keep.sum()), reason="empty_value")
    state = {"outliers_total": 0, "outliers_shown": 0}
    boxes: list[dict[str, Any]] = []
    if ccol is None:
        v = raw.filter(keep)
        if len(v):
            boxes.append(_box(name, v, spec.options.outliers, state))
    else:
        work = frame.select(pl.col(ccol).alias("__g"), raw.alias("__v")).filter(keep)
        keys = category_values(work["__g"])
        order = list(dict.fromkeys(keys))
        if len(order) > MAX_BOX_GROUPS:
            raise DataOpsError("chart_too_many_categories", f"{len(order)} groups (limit {MAX_BOX_GROUPS})",
                               path=pointer("series", 0, "category_col"), hint="filter the data, or choose a column with fewer groups")
        by_key = pl.DataFrame({"k": [str(k) for k in keys], "v": work["__v"]})
        for key in order:
            boxes.append(_box(str(key) if not isinstance(key, float) else f"{key:g}", by_key.filter(pl.col("k") == str(key))["v"],
                              spec.options.outliers, state))
    cats: list[str | float] = [b["category"] for b in boxes]
    meds: list[Optional[float]] = [b["median"] for b in boxes]
    if spec.sort is not None and boxes:  # "by value" sorts by the median
        axis, vals = apply_order(Axis(cats), [meds], order_axis(Axis(cats), [meds], spec.sort))
        pos = {c: i for i, c in enumerate(cats)}
        boxes = [boxes[pos[c]] for c in axis.cats]
        cats, meds = list(axis.cats), vals[0]
    small = sum(1 for b in boxes if b["n"] < SMALL_SAMPLE)
    if small:
        notes.add("small_sample", count=small, minimum=SMALL_SAMPLE)
    if state["outliers_total"]:
        notes.add("outliers_limited", shown=state["outliers_shown"], total=state["outliers_total"])
    if len(cats) > MAX_CATEGORIES:  # unreachable with MAX_BOX_GROUPS, kept as a guard for future limits
        raise DataOpsError("chart_too_many_categories", f"{len(cats)} groups", path=pointer("series", 0, "category_col"))
    return ChartData(categories=cats, series=[{"name": name, "values": meds}], categories_kind="category", notes=notes.items,
                     meta={"kind": "boxplot", "boxes": boxes, "whisker": f"{WHISKER_IQR:g}xIQR", "quartiles": "linear"})
