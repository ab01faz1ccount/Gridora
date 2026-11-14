from __future__ import annotations

import datetime as dt
import itertools
import json
from pathlib import Path

import polars as pl
import pytest
from fakes import FakeExecContext, txt
from gridora_contracts.models import DateValue, Operation, SheetRangeTarget
from hypothesis import given, settings
from hypothesis import strategies as st

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.convert_calendar import CalendarParams, ConvertCalendarOp
from gridora_dataops.persian import jalali as J
from gridora_dataops.spec import PlanEnv

GOLD = json.loads((Path(__file__).parent / "golden" / "jalali_vectors.json").read_text(encoding="utf-8"))


def test_vectors_from_independent_implementations() -> None:
    """Expected values were generated once from jdatetime and persiantools (see the file's provenance)."""
    ys = pl.Series([v[0] for v in GOLD["vectors"]])
    ms = pl.Series([v[1] for v in GOLD["vectors"]])
    ds = pl.Series([v[2] for v in GOLD["vectors"]])
    expected = [dt.date.fromisoformat(v[3]) for v in GOLD["vectors"]]
    assert J.from_jalali(ys, ms, ds).to_list() == expected
    back = J.to_jalali(pl.Series(expected, dtype=pl.Date))
    assert list(zip(back["year"], back["month"], back["day"], strict=True)) == [tuple(v[:3]) for v in GOLD["vectors"]]


def test_every_year_start_matches_the_oracles() -> None:
    for y, iso in GOLD["year_starts"].items():
        assert J.STARTS[int(y) - J.MIN_YEAR] == (dt.date.fromisoformat(iso) - dt.date(1970, 1, 1)).days, y


def test_known_dates_and_leap_years() -> None:
    d = pl.Series([dt.date(2024, 3, 20), dt.date(2025, 3, 20), dt.date(2025, 3, 21), dt.date(2026, 11, 14)], dtype=pl.Date)
    r = J.to_jalali(d)
    assert list(zip(r["year"], r["month"], r["day"], strict=True)) == [(1403, 1, 1), (1403, 12, 30), (1404, 1, 1), (1405, 8, 23)]
    assert [y for y in range(1395, 1410) if J.is_leap(y)] == [1395, 1399, 1403, 1408]


def test_invalid_and_out_of_range_are_null_not_guessed() -> None:
    got = J.from_jalali(pl.Series([1403, 1403, 1403, 1404, 1299, 1501, 1403]), pl.Series([12, 12, 13, 12, 1, 1, 0]),
                        pl.Series([30, 31, 1, 30, 1, 1, 1])).to_list()
    assert got == [dt.date(2025, 3, 20), None, None, None, None, None, None]
    r = J.to_jalali(pl.Series([dt.date(1900, 1, 1), dt.date(2200, 1, 1), None], dtype=pl.Date))
    assert r["year"].to_list() == [None, None, None]


@settings(max_examples=200, deadline=None)
@given(st.dates(min_value=dt.date(1921, 3, 21), max_value=dt.date(2122, 3, 19)))
def test_round_trip_over_the_supported_range(d: dt.date) -> None:
    r = J.to_jalali(pl.Series([d], dtype=pl.Date))
    assert J.from_jalali(r["year"], r["month"], r["day"]).to_list() == [d]
    assert 1 <= r["month"][0] <= 12 and 1 <= r["day"][0] <= 31


def test_consecutive_days_advance_by_one() -> None:
    days = pl.Series([dt.date(2024, 1, 1) + dt.timedelta(n) for n in range(800)], dtype=pl.Date)
    r = J.to_jalali(days)
    lin = (r["year"] * 372 + (r["month"] - 1) * 31 + r["day"]).to_list()
    assert all(b > a for a, b in itertools.pairwise(lin))  # strictly increasing: no skips backwards, no repeats


# ------------------------------------------------------------ operation
def conv(df: pl.DataFrame, **p):  # type: ignore[no-untyped-def]
    return ConvertCalendarOp().plan(df, CalendarParams.model_validate({"column": "d", **p}), PlanEnv())


def test_to_jalali_text_digits_parts_and_new_column() -> None:
    df = pl.DataFrame({"d": [dt.date(2024, 3, 20), None, dt.date(2025, 3, 20)], "k": [1, 2, 3]})
    assert conv(df).frame["d"].to_list() == ["۱۴۰۳/۰۱/۰۱", None, "۱۴۰۳/۱۲/۳۰"]
    assert conv(df, digits="latin").frame["d"].to_list() == ["1403/01/01", None, "1403/12/30"]
    out = conv(df, format="parts").frame
    assert out.columns == ["d_year", "d_month", "d_day", "k"] and out.row(2) == (1403, 12, 30, 3)
    out = conv(df, output_column="j", digits="latin").frame
    assert out.columns == ["d", "j", "k"] and out["d"].to_list() == df["d"].to_list()
    with pytest.raises(DataOpsError) as e:
        conv(df, output_column="k")
    assert e.value.errors[0].path == "/params/output_column"


def test_datetimes_use_their_date_part() -> None:
    df = pl.DataFrame({"d": [dt.datetime(2024, 3, 20, 23, 59)]})
    assert conv(df, digits="latin").frame["d"].to_list() == ["1403/01/01"]


def test_from_jalali_accepts_every_digit_script_and_separator() -> None:
    df = pl.DataFrame({"d": ["1403/01/01", "۱۴۰۳-۱۲-۳۰", "١٤٠٤.٠١.٠١", " 1403/1/2 ", "", None]})
    assert conv(df, direction="from_jalali").frame["d"].to_list() == [
        dt.date(2024, 3, 20), dt.date(2025, 3, 20), dt.date(2025, 3, 21), dt.date(2024, 3, 21), None, None]


def test_unconvertible_values_fail_with_examples_or_become_empty() -> None:
    df = pl.DataFrame({"d": ["1404/12/30", "1403/13/01", "abc", "1403/01/01"]})
    with pytest.raises(DataOpsError) as e:
        conv(df, direction="from_jalali")
    err = e.value.errors[0]
    assert err.code == "type_mismatch" and "3 value(s)" in err.message and "1404/12/30" in (err.hint or "")
    out = conv(df, direction="from_jalali", on_error="null")
    assert out.frame["d"].to_list() == [None, None, None, dt.date(2024, 3, 20)]
    assert [w.code for w in out.warnings] == ["values_set_to_null"]
    with pytest.raises(DataOpsError):
        conv(pl.DataFrame({"d": [dt.date(1900, 1, 1)]}))  # outside the supported range


def test_wrong_column_types_are_rejected_with_a_hint() -> None:
    with pytest.raises(DataOpsError) as e:
        conv(pl.DataFrame({"d": ["2024-03-20"]}))
    assert e.value.errors[0].path == "/params/column" and "change_type" in (e.value.errors[0].hint or "")
    with pytest.raises(DataOpsError):
        conv(pl.DataFrame({"d": [1.0]}), direction="from_jalali")


def test_round_trip_through_the_operation() -> None:
    days = [dt.date(1921, 3, 21) + dt.timedelta(n * 97) for n in range(750)]
    df = pl.DataFrame({"d": days})
    j = conv(df, digits="latin").frame
    assert conv(j, direction="from_jalali").frame["d"].to_list() == days


def test_on_a_sheet_writes_text_and_undoes() -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("when")], [DateValue(iso="2024-03-20")], [DateValue(iso="2025-03-21")]])
    original = ctx.snapshot()
    op = Operation(type="convert_calendar", target=SheetRangeTarget(range=ctx.rng(0, 0, 2, 0)),
                   params={"column": "when", "digits": "latin"})
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "ok" and [ctx.grid[(r, 0)].v for r in (1, 2)] == [txt("1403/01/01"), txt("1404/01/01")]
    ctx.apply_delta(res.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original
