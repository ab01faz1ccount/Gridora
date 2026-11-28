"""Column facts and chart suggestions for the Chart Builder.

Cheap and deterministic on purpose: a few counts, min/max, a regex look at text that may be dates, and a handful of
name hints. It never decides for the person (every role stays changeable) and never calls anything smarter."""
from __future__ import annotations

import re
from typing import Literal, Optional

import polars as pl
from gridora_contracts.models import (
    ChartColumnProfile,
    ChartLimit,
    ChartProfile,
    ChartSeries,
    ChartSuggestion,
    ChartTime,
)

from ..persian.chars import variant_fold

MAX_SUGGESTIONS = 5
MAX_SERIES_SUGGESTED = 3
MANY_CATEGORIES = 30
MAX_BOX_GROUPS_SUGGESTED = 12
BOX_MIN_PER_GROUP = 5  # a box plot of fewer values than this per group says little
SAMPLE = 500
_DATE_TEXT = re.compile(r"^(\d{3,4})[/\-.](\d{1,2})[/\-.](\d{1,2})$")
_ID_NAME = re.compile(r"(^|[\s_\-.])(id|code|no|number|uuid)($|[\s_\-.])|شناسه|کد|شماره", re.IGNORECASE)
_AVG_NAME = re.compile(r"age|rate|ratio|price|score|avg|average|mean|percent|pct|سن|نرخ|قیمت|نمره|درصد|میانگین|امتیاز", re.IGNORECASE)


def _date_text_calendar(s: pl.Series) -> Optional[Literal["gregorian", "jalali"]]:
    """'jalali' / 'gregorian' when (almost) every non-empty text value looks like y/m/d, else None."""
    vals = [v.strip() for v in s.drop_nulls().head(SAMPLE * 4).to_list() if v.strip()][:SAMPLE]
    if not vals:
        return None
    folded = pl.Series("v", vals).to_frame().select(variant_fold(pl.col("v")))["v"].to_list()  # any digit script
    counts = {"jalali": 0, "gregorian": 0}
    for v in folded:
        m = _DATE_TEXT.match(v)
        if not m:
            continue
        y, mo, d = (int(g) for g in m.groups())
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        if 1200 <= y <= 1600:
            counts["jalali"] += 1
        elif 1700 <= y <= 2200:
            counts["gregorian"] += 1
    best: Literal["gregorian", "jalali"] = "jalali" if counts["jalali"] >= counts["gregorian"] else "gregorian"
    return best if counts[best] >= 0.9 * len(vals) else None


def _column(index: int, name: str, s: pl.Series) -> ChartColumnProfile:
    dtype = s.dtype
    blanks = int((s.str.strip_chars() == "").sum() or 0) if dtype == pl.String else 0
    nulls = s.null_count() + blanks
    rows = len(s)
    kind = ("bool" if dtype == pl.Boolean else "number" if dtype.is_numeric() else
            "date" if dtype == pl.Date or isinstance(dtype, pl.Datetime) else "text")
    if nulls == rows:
        kind = "empty"
    live = s.drop_nulls()
    if dtype == pl.String:
        live = live.filter(live.str.strip_chars() != "")
    prof = ChartColumnProfile(index=index, name=name, kind=kind, nulls=nulls, distinct=live.n_unique() if len(live) else 0)
    if kind == "number":
        finite = live.filter(live.is_finite()) if dtype.is_float() else live
        if len(finite):
            prof.min, prof.max, prof.mean = float(finite.min()), float(finite.max()), float(finite.mean())  # type: ignore[arg-type]
    elif kind == "date" and len(live):
        prof.min, prof.max = live.min().isoformat(), live.max().isoformat()  # type: ignore[union-attr]
    elif kind == "text":
        prof.date_text = _date_text_calendar(live)
    prof.looks_like = _role(prof, live)
    if prof.looks_like == "measure":
        prof.default_aggregate = "avg" if _AVG_NAME.search(name) else "sum"
    elif prof.looks_like == "identifier":
        prof.default_aggregate = "count"
    return prof


Role = Optional[Literal["category", "measure", "time", "identifier"]]


def _role(p: ChartColumnProfile, live: pl.Series) -> Role:
    if p.kind == "empty":
        return None
    if p.kind == "date" or p.date_text:
        return "time"
    if p.kind == "bool":
        return "category"
    if p.kind == "number":
        whole = bool(len(live)) and (live.dtype.is_integer() or bool((live.cast(pl.Float64) % 1 == 0).all()))
        # a plain row counter (1, 2, 3, ...) is an identifier; other unique whole numbers may well be measures
        counter = whole and len(live) >= 3 and p.distinct == len(live) and float(live.max()) - float(live.min()) == len(live) - 1  # type: ignore[arg-type]
        return "identifier" if _ID_NAME.search(p.name) or counter else "measure"
    n = len(live)
    return "identifier" if p.distinct > 200 and p.distinct >= 0.9 * n else "category"


def _suggestions(cols: list[ChartColumnProfile], rows: int) -> list[ChartSuggestion]:
    times = [c for c in cols if c.looks_like == "time"]
    cats = [c for c in cols if c.looks_like == "category"]
    meas = [c for c in cols if c.looks_like == "measure"]
    out: list[ChartSuggestion] = []

    def series(by: ChartColumnProfile) -> list[ChartSeries]:
        return [ChartSeries(name=m.name, value_col=m.index, category_col=by.index, aggregate=m.default_aggregate or "sum")
                for m in meas[:MAX_SERIES_SUGGESTED]]

    if times and meas:
        t = times[0]
        cal = "jalali" if t.date_text == "jalali" else "gregorian"
        out.append(ChartSuggestion(type="line", series=series(t), reason="time_and_number",
                                   time=ChartTime(calendar=cal, granularity="month" if t.distinct > 60 else None)))
    if cats and meas:
        c = cats[0]
        limit = ChartLimit(top_n=15) if c.distinct > MANY_CATEGORIES else None
        out.append(ChartSuggestion(type="bar", series=series(c), reason="category_and_number", limit=limit))
        first = meas[0]
        if 2 <= c.distinct <= 8 and first.min is not None and float(first.min) >= 0:
            out.append(ChartSuggestion(type="pie", reason="share_of_total", series=series(c)[:1]))
    if len(meas) >= 2:
        x, y = meas[0], meas[1]
        out.append(ChartSuggestion(type="scatter", reason="two_numbers",
                                   series=[ChartSeries(name=y.name, value_col=y.index, category_col=x.index)]))
    if meas:  # one number: how are its values spread?
        m = meas[0]
        out.append(ChartSuggestion(type="histogram", reason="one_number", series=[ChartSeries(name=m.name, value_col=m.index)]))
    if cats and meas and rows >= BOX_MIN_PER_GROUP * max(2, cats[0].distinct) and 2 <= cats[0].distinct <= MAX_BOX_GROUPS_SUGGESTED:
        out.append(ChartSuggestion(type="boxplot", reason="distribution_by_category",
                                   series=[ChartSeries(name=meas[0].name, value_col=meas[0].index, category_col=cats[0].index)]))
    return out[:MAX_SUGGESTIONS]


def profile_frame(frame: pl.DataFrame) -> ChartProfile:
    cols = [_column(i, name, frame[name]) for i, name in enumerate(frame.columns)]
    return ChartProfile(rows=frame.height, columns=cols, suggestions=_suggestions(cols, frame.height))


__all__ = ["profile_frame"]
