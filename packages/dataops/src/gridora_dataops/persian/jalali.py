"""Gregorian <-> Jalali (Solar Hijri) conversion, vectorised.

Rule: the 33-year arithmetic cycle (leap years are those with year % 33 in {1,5,9,13,17,22,26,30}), anchored on
1 Farvardin 1403 = 2024-03-20. Verified (see tests/golden/jalali_vectors.json and PLAN.md) against three independent
implementations for every year of the supported range. **Supported range: Jalali years 1300..1500** (Gregorian
1921-03-21 .. 2122-03-20); dates outside it are reported as unconvertible rather than guessed. The official calendar
is astronomical, so the arithmetic rule may diverge from it in years far outside this range.
"""
from __future__ import annotations

import polars as pl

MIN_YEAR = 1300
MAX_YEAR = 1500
_LEAP_RESIDUES = (1, 5, 9, 13, 17, 22, 26, 30)
_ANCHOR_YEAR = 1403
_ANCHOR_DAYS = 19802  # 2024-03-20 as days since 1970-01-01


def is_leap(year: int) -> bool:
    return year % 33 in _LEAP_RESIDUES


def _starts() -> list[int]:
    """Epoch day of 1 Farvardin for every year MIN_YEAR..MAX_YEAR+1."""
    start = {_ANCHOR_YEAR: _ANCHOR_DAYS}
    for y in range(_ANCHOR_YEAR - 1, MIN_YEAR - 1, -1):
        start[y] = start[y + 1] - (366 if is_leap(y) else 365)
    for y in range(_ANCHOR_YEAR, MAX_YEAR + 1):
        start[y + 1] = start[y] + (366 if is_leap(y) else 365)
    return [start[y] for y in range(MIN_YEAR, MAX_YEAR + 2)]


STARTS = _starts()
_STARTS_S = pl.Series("starts", STARTS, dtype=pl.Int64)


def _leap_expr(year: pl.Expr) -> pl.Expr:
    return (year % 33).is_in(list(_LEAP_RESIDUES))


def _month_start(month: pl.Expr) -> pl.Expr:
    """0-based day of year on which `month` starts."""
    return pl.when(month <= 6).then((month - 1) * 31).otherwise(186 + (month - 7) * 30)


def to_jalali(dates: pl.Series) -> pl.DataFrame:
    """Columns year, month, day (Int64, null where the date is null or outside the supported range)."""
    days = dates.cast(pl.Int32).cast(pl.Int64)
    ok = (days >= STARTS[0]) & (days < STARTS[-1])
    idx = (_STARTS_S.search_sorted(days.fill_null(STARTS[0]), side="right").cast(pl.Int64) - 1).clip(0, len(STARTS) - 2)
    doy = days - _STARTS_S.gather(idx)
    df = pl.DataFrame({"year": idx + MIN_YEAR, "doy": doy, "ok": ok})
    month = (pl.when(pl.col("doy") < 186).then(pl.col("doy") // 31 + 1)
             .otherwise(pl.min_horizontal((pl.col("doy") - 186) // 30 + 7, pl.lit(12, dtype=pl.Int64))))
    df = df.with_columns(month.alias("month"))
    day = pl.col("doy") - _month_start(pl.col("month")) + 1
    out = df.with_columns(day.alias("day")).select(
        pl.when(pl.col("ok")).then(pl.col("year")).alias("year"),
        pl.when(pl.col("ok")).then(pl.col("month")).alias("month"),
        pl.when(pl.col("ok")).then(pl.col("day")).alias("day"))
    return out.with_columns(pl.when(dates.is_not_null()).then(pl.all()))


def from_jalali(year: pl.Series, month: pl.Series, day: pl.Series) -> pl.Series:
    """Date series; null for invalid month/day or years outside the supported range."""
    df = pl.DataFrame({"y": year.cast(pl.Int64), "m": month.cast(pl.Int64), "d": day.cast(pl.Int64)})
    y, m, d = pl.col("y"), pl.col("m"), pl.col("d")
    length = pl.when(m <= 6).then(31).when(m <= 11).then(30).when(_leap_expr(y)).then(30).otherwise(29)
    valid = y.is_between(MIN_YEAR, MAX_YEAR) & m.is_between(1, 12) & (d >= 1) & (d <= length)
    start = pl.lit(_STARTS_S).gather((y - MIN_YEAR).clip(0, len(STARTS) - 1))
    days = df.select(pl.when(valid).then(start + _month_start(m) + d - 1).alias("days"))["days"]
    return days.cast(pl.Int32).cast(pl.Date).alias("date")


_LATIN = "0123456789"
_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"


def format_jalali(year: pl.Series, month: pl.Series, day: pl.Series, *, persian_digits: bool) -> pl.Series:
    df = pl.DataFrame({"y": year, "m": month, "d": day}).select(
        pl.format("{}/{}/{}", pl.col("y").cast(pl.String).str.zfill(4), pl.col("m").cast(pl.String).str.zfill(2),
                  pl.col("d").cast(pl.String).str.zfill(2)).alias("t"),
        (pl.col("y").is_null() | pl.col("m").is_null() | pl.col("d").is_null()).alias("null"))
    text: pl.Expr = pl.when(~pl.col("null")).then(pl.col("t"))
    if persian_digits:
        text = text.str.replace_many(list(_LATIN), list(_PERSIAN))
    return df.select(text.alias("jalali"))["jalali"]
