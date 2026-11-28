"""Order, Top N and "Other" for category charts, on the small prepared table (never on the source rows)."""
from __future__ import annotations

from typing import Optional

import polars as pl
from gridora_contracts.models import ChartLimit, ChartSort

from ..analytics import NULL_CATEGORY
from ..errors import DataOpsError, pointer
from ..persian.chars import collation_key
from .common import OTHER_CATEGORY, Axis, Cat, Notes


def totals(series: list[list[Optional[float]]], n: int) -> list[Optional[float]]:
    """Sum of the series values of each category; None when every series is empty there."""
    out: list[Optional[float]] = []
    for i in range(n):
        vals = [v for s in series if (v := s[i]) is not None]
        out.append(sum(vals) if vals else None)
    return out


def _same(a: Cat, b: Cat) -> bool:
    return a == b if isinstance(a, float) and isinstance(b, float) else str(a) == str(b)


def _category_order(cats: list[Cat], kind: str, descending: bool) -> list[int]:
    """Indexes in category order: numbers by value, text by Persian collation, the empty category last."""
    idx = list(range(len(cats)))
    nums = [i for i in idx if isinstance(cats[i], float)]
    text = [i for i in idx if isinstance(cats[i], str) and cats[i] != NULL_CATEGORY]
    empty = [i for i in idx if cats[i] == NULL_CATEGORY]
    nums.sort(key=lambda i: float(cats[i]))
    if text:
        if kind == "time":  # ISO dates sort correctly as text
            text.sort(key=lambda i: str(cats[i]))
        else:
            df = pl.DataFrame({"c": [str(cats[i]) for i in text]}).with_row_index("p")
            order = df.with_columns(collation_key(pl.col("c")).alias("k")).sort("k", maintain_order=True)["p"].to_list()
            text = [text[p] for p in order]
    body = nums + text
    if descending:
        body.reverse()
    return body + empty


def order_axis(axis: Axis, values: list[list[Optional[float]]], sort: ChartSort) -> list[int]:
    n = len(axis.cats)
    desc = sort.direction == "desc"
    if sort.order:
        rank: list[int] = []
        for want in sort.order:
            for i in range(n):
                if _same(axis.cats[i], want) and i not in rank:
                    rank.append(i)
        return rank + [i for i in range(n) if i not in rank]
    by = "category" if sort.by == "source" and axis.kind == "time" else sort.by  # "source order" of dates is time
    if by == "source":
        return list(range(n))
    if by == "category":
        return _category_order(axis.cats, axis.kind, desc)
    tot = totals(values, n)
    present = [i for i in range(n) if tot[i] is not None]
    missing = [i for i in range(n) if tot[i] is None]
    present.sort(key=lambda i: tot[i], reverse=desc)  # type: ignore[arg-type,return-value]  # stable: ties keep source order
    return present + missing


def apply_order(axis: Axis, values: list[list[Optional[float]]], order: list[int]) -> tuple[Axis, list[list[Optional[float]]]]:
    return (Axis([axis.cats[i] for i in order], axis.kind, [axis.labels[i] for i in order] if axis.labels else None),
            [[s[i] for i in order] for s in values])


def apply_limit(axis: Axis, values: list[list[Optional[float]]], limit: ChartLimit, additive: bool, notes: Notes,
                keep_order: bool) -> tuple[Axis, list[list[Optional[float]]]]:
    """Keep the top/bottom N categories by value. `other` adds up the rest (only valid for sums and counts)."""
    n = len(axis.cats)
    if axis.kind == "time":
        raise DataOpsError("invalid_param", "Top N does not apply to a time axis", path=pointer("limit"),
                           hint="use a date range filter or a larger time step instead")
    if limit.other and not additive:
        raise DataOpsError("invalid_param", "\"Other\" can only add up sums and counts", path=pointer("limit", "other"),
                           hint="turn off \"Other\" or aggregate with sum or count")
    if n <= limit.top_n:
        return axis, values
    tot = totals(values, n)
    ranked = sorted((i for i in range(n) if tot[i] is not None), key=lambda i: tot[i], reverse=limit.end == "top")  # type: ignore[arg-type,return-value]
    ranked += [i for i in range(n) if tot[i] is None]
    kept, rest = ranked[: limit.top_n], ranked[limit.top_n:]
    if keep_order:
        kept.sort()
    cats = [axis.cats[i] for i in kept]
    labels = [axis.labels[i] for i in kept] if axis.labels else None
    out = [[s[i] for i in kept] for s in values]
    notes.add("categories_limited", shown=len(kept), total=n)
    if limit.other and rest:
        cats.append(OTHER_CATEGORY)
        if labels is not None:
            labels.append(OTHER_CATEGORY)
        for s_out, s_in in zip(out, values, strict=True):
            vals = [v for i in rest if (v := s_in[i]) is not None]
            s_out.append(sum(vals) if vals else None)
        notes.add("other_merged", count=len(rest))
    return Axis(cats, axis.kind, labels), out
