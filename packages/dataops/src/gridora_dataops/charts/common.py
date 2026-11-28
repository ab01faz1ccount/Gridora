"""Shared building blocks of the chart adapters: column lookup, filters, null-aware aggregation, dates.

Nothing here knows a chart type. Each adapter (adapters.py) decides what data its chart needs and uses these."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import polars as pl
from gridora_contracts.models import ChartFilter, ChartNote, ChartTime

from ..analytics import NULL_CATEGORY, AggSpec, aggregate
from ..errors import DataOpsError, pointer
from ..ops.filter import Condition, condition_predicate
from ..persian.chars import variant_fold
from ..persian.jalali import format_jalali, from_jalali, to_jalali

MAX_CATEGORIES = 5000
MAX_SERIES = 30
MAX_SCATTER_POINTS = 5000
OTHER_CATEGORY = "سایر"
COUNT_LIKE = ("count", "count_distinct")
Cat = Union[str, float]


@dataclass
class Axis:
    """Category side of a chart: values, how to draw them, and what kind of axis it is."""
    cats: list[Cat]
    kind: str = "category"  # category | time | number
    labels: Optional[list[str]] = None


@dataclass
class Notes:
    items: list[ChartNote] = field(default_factory=list)

    def add(self, code: str, **params: Any) -> None:
        self.items.append(ChartNote(code=code, params=params))


def resolve(frame: pl.DataFrame, ref: Union[str, int], ptr: str) -> str:
    if isinstance(ref, int):
        if not 0 <= ref < frame.width:
            raise DataOpsError("unknown_column", f"column index {ref} is out of range", path=ptr)
        return frame.columns[ref]
    if ref not in frame.columns:
        raise DataOpsError("unknown_column", f"column '{ref}' does not exist", path=ptr)
    return ref


def category_values(s: pl.Series) -> list[Cat]:
    out: list[Cat] = []
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


def numbers(s: pl.Series) -> list[Optional[float]]:
    return [None if v is None or (isinstance(v, float) and not math.isfinite(v)) else float(v) for v in s.to_list()]


def apply_filters(frame: pl.DataFrame, filters: list[ChartFilter]) -> pl.DataFrame:
    """The chart's own row tests (AND). They never touch the source data, only what the chart reads."""
    if not filters:
        return frame
    tests = []
    for i, f in enumerate(filters):
        col = resolve(frame, f.column, pointer("filters", i, "column"))
        cond = Condition(column=col, op=f.op, value=f.value, value2=f.value2)
        tests.append(condition_predicate(cond, frame.schema, pointer("filters", i)))
    return frame.filter(pl.all_horizontal(tests))


def need_numeric(frame: pl.DataFrame, col: str, ptr: str, what: str) -> None:
    if not frame.schema[col].is_numeric():
        raise DataOpsError("type_mismatch", f"{what} '{col}' must be numeric", path=ptr)


def aggregate_values(frame: pl.DataFrame, by: list[str], fn: str, vcol: str, ptr: str) -> pl.DataFrame:
    """Group `by` and aggregate `vcol` into `__v`. A group whose values are all empty is EMPTY (None), not 0:
    sum/average/min/max/median of nothing is not a number (counts are real zeros)."""
    aggs = [AggSpec(fn, vcol, "__v")]
    if fn not in COUNT_LIKE:
        aggs.append(AggSpec("count", vcol, "__n"))
    out = aggregate(frame, by, aggs, ptr=ptr)
    if "__n" in out.columns:
        out = out.with_columns(pl.when(pl.col("__n") == 0).then(None).otherwise(pl.col("__v")).alias("__v")).drop("__n")
    return out


# ------------------------------------------------------------------ dates
_JALALI_TEXT = r"^(\d{3,4})/(\d{1,2})/(\d{1,2})$"


def is_temporal(dtype: pl.DataType) -> bool:
    return dtype == pl.Date or isinstance(dtype, pl.Datetime)


def _to_dates(s: pl.Series, time: Optional[ChartTime]) -> pl.Series:
    """Date series from a date column, or from text when the chart says how to read it (null = unreadable/empty)."""
    if s.dtype == pl.Date:
        return s
    if isinstance(s.dtype, pl.Datetime):
        return s.dt.date()
    text = s.to_frame("t").select(variant_fold(pl.col("t").str.strip_chars()).str.replace_all(r"[-.]", "/").alias("t"))["t"]
    if time is not None and time.calendar == "jalali":
        m = text.str.extract_groups(_JALALI_TEXT)
        y, mo, d = (m.struct.field(str(i)).cast(pl.Int64, strict=False) for i in (1, 2, 3))
        return from_jalali(y, mo, d)
    return text.str.replace_all("/", "-").str.to_date(strict=False)


def _bucket(dates: pl.Series, time: ChartTime) -> tuple[pl.Series, pl.Series]:
    """(bucket start date, label) per row. Rows whose date cannot be placed get null in both."""
    gran = time.granularity or "day"
    if time.calendar == "gregorian":
        start = dates if gran == "day" else dates.dt.truncate({"month": "1mo", "quarter": "1q", "year": "1y"}[gran])
        df = pl.DataFrame({"d": start})
        if gran == "quarter":
            lab = df.select(pl.format("{}-Q{}", pl.col("d").dt.year(), pl.col("d").dt.quarter()).alias("l"))["l"]
        else:
            lab = df.select(pl.col("d").dt.strftime({"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[gran]).alias("l"))["l"]
        return start, lab
    parts = to_jalali(dates)
    y, mo, d = parts["year"], parts["month"], parts["day"]
    if gran == "day":
        return from_jalali(y, mo, d), format_jalali(y, mo, d, persian_digits=False)
    first = [None if m is None else (1 if gran == "year" else (m - 1) // 3 * 3 + 1 if gran == "quarter" else m)
             for m in mo.to_list()]
    start = from_jalali(y, pl.Series(first, dtype=pl.Int64), pl.Series([1] * len(y), dtype=pl.Int64))
    labs = [None if yy is None else f"{yy:04d}" if gran == "year" else f"{yy:04d}/{mm:02d}" if gran == "month"
            else f"{yy:04d}-Q{(mm - 1) // 3 + 1}" for yy, mm in zip(y.to_list(), mo.to_list(), strict=True)]
    return start, pl.Series("l", labs, dtype=pl.String)


def time_axis(frame: pl.DataFrame, ccol: str, time: Optional[ChartTime], notes: Notes, ptr: str
              ) -> tuple[pl.DataFrame, Optional[dict[str, str]]]:
    """Make the category column a real date axis when it is one (or when the chart says to read it as dates).
    Returns the frame with `ccol` replaced by the bucket start date, and {iso date -> label}; (frame, None) when
    the column is not a time axis. Rows without a usable date are left out and counted in a note."""
    dtype = frame.schema[ccol]
    if not (is_temporal(dtype) or (time is not None and dtype == pl.String)):
        return frame, None
    cfg = time or ChartTime()
    src = frame[ccol]
    dates = _to_dates(src, cfg)
    nonblank = src.is_not_null() if src.dtype != pl.String else (src.is_not_null() & (src.str.strip_chars() != ""))
    start, lab = _bucket(dates, cfg)
    unreadable = nonblank & start.is_null()
    empty = ~nonblank
    n_bad, n_empty = int(unreadable.sum()), int(empty.sum())
    if n_bad:
        ex = [str(x) for x in src.filter(unreadable).head(3).to_list()]
        notes.add("dates_unreadable", count=n_bad, examples=ex)
    if n_empty:
        notes.add("rows_excluded", count=n_empty, reason="empty_date")
    keep = start.is_not_null()
    out = frame.with_columns(start.alias(ccol)).filter(keep)
    labels = dict(zip((d.isoformat() for d in start.filter(keep).to_list()), lab.filter(keep).to_list(), strict=True))
    return out, labels
