from __future__ import annotations

import datetime as dt

import polars as pl
import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import Operation, SheetRangeTarget
from hypothesis import given, settings
from hypothesis import strategies as st

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.change_type import ChangeTypeOp, ChangeTypeParams
from gridora_dataops.spec import PlanEnv


def conv(values: list, dtype=pl.String, **p):  # type: ignore[no-untyped-def]
    df = pl.DataFrame({"c": values}, schema={"c": dtype})
    out = ChangeTypeOp().plan(df, ChangeTypeParams.model_validate({"column": "c", **p}), PlanEnv())
    return out.frame["c"].to_list(), out


@pytest.mark.parametrize(("text", "expected"), [
    ("۱۲۳", 123), ("١٢٣", 123), ("1,234", 1234), ("۱٬۲۳۴", 1234), ("۱،۲۳۴", 1234), (" 12 ", 12),
    ("3.0", 3), ("-5", -5), ("1 234", 1234),
])
def test_text_to_int(text: str, expected: int) -> None:
    assert conv([text], to="int64")[0] == [expected]


def test_text_to_float_with_arabic_decimal_separator_and_explicit_comma() -> None:
    assert conv(["۱٫۵", "2.25", "1,000.5"], to="float64")[0] == [1.5, 2.25, 1000.5]
    assert conv(["1,5", "1.234,5"], to="float64", decimal_separator="comma")[0] == [1.5, 1234.5]
    assert conv(["1,5"], to="float64")[0] == [15.0]  # documented: comma is a thousands separator unless told otherwise


def test_blank_text_is_empty_not_an_error() -> None:
    assert conv(["", "  ", None, "7"], to="int64")[0] == [None, None, None, 7]


def test_failures_stop_the_operation_with_a_count_and_examples() -> None:
    with pytest.raises(DataOpsError) as e:
        conv(["1", "x", "y", "2"], to="int64")
    err = e.value.errors[0]
    assert (err.code, err.path) == ("type_mismatch", "/params/column")
    assert "2 value(s)" in err.message and "x; y" in (err.hint or "")


def test_on_error_null_keeps_going_and_warns() -> None:
    values, out = conv(["1", "x", "3"], to="int64", on_error="null")
    assert values == [1, None, 3] and [w.code for w in out.warnings] == ["values_set_to_null"]


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "1e400"])
def test_non_finite_numbers_are_rejected(bad: str) -> None:
    assert conv([bad], to="float64", on_error="null")[0] == [None]


def test_int_rules() -> None:
    assert conv([1.0, 2.0, None], pl.Float64, to="int64")[0] == [1, 2, None]
    with pytest.raises(DataOpsError):
        conv([1.5], pl.Float64, to="int64")
    assert conv([1.5], pl.Float64, to="int64", on_error="null")[0] == [None]
    assert conv([9007199254740993], pl.Int64, to="float64")[0] == [9007199254740992.0]  # documented 2^53 limit


def test_number_to_text_has_no_trailing_zero() -> None:
    assert conv([3.0, 1.5, None], pl.Float64, to="string")[0] == ["3", "1.5", None]
    assert conv([7], pl.Int64, to="string")[0] == ["7"]


def test_bool_words_in_persian_and_english() -> None:
    assert conv(["بله", "خیر", "TRUE", " no ", "۱", "0"], to="bool")[0] == [True, False, True, False, True, False]
    with pytest.raises(DataOpsError):
        conv(["شاید"], to="bool")
    assert conv([0.0, 1.0], pl.Float64, to="bool")[0] == [False, True]
    assert conv([True, False], pl.Boolean, to="string")[0] == ["true", "false"]


def test_dates() -> None:
    assert conv(["2024-03-01", "2024/03/02", "۲۰۲۴-۰۳-۰۳", "2024.03.04"], to="date")[0] == [
        dt.date(2024, 3, 1), dt.date(2024, 3, 2), dt.date(2024, 3, 3), dt.date(2024, 3, 4)]
    assert conv(["01/03/2024"], to="date", date_format="%d/%m/%Y")[0] == [dt.date(2024, 3, 1)]
    with pytest.raises(DataOpsError):
        conv(["not a date"], to="date")
    assert conv([dt.date(2024, 1, 5)], pl.Date, to="string")[0] == ["2024-01-05"]
    assert conv([dt.date(2024, 1, 5)], pl.Date, to="datetime")[0] == [dt.datetime(2024, 1, 5)]
    assert conv(["2024-01-05 10:30:00", "2024-01-05T10:30", "2024-01-05"], to="datetime")[0] == [
        dt.datetime(2024, 1, 5, 10, 30), dt.datetime(2024, 1, 5, 10, 30), dt.datetime(2024, 1, 5)]


def test_unsupported_conversion_points_at_the_type_parameter() -> None:
    with pytest.raises(DataOpsError) as e:
        conv([dt.date(2024, 1, 5)], pl.Date, to="int64")
    assert (e.value.errors[0].code, e.value.errors[0].path) == ("type_mismatch", "/params/to")


def test_same_type_is_a_no_op() -> None:
    assert conv(["a"], to="string")[0] == ["a"]


@settings(max_examples=80, deadline=None)
@given(st.integers(-10**12, 10**12), st.sampled_from(["latin", "persian", "arabic"]), st.booleans())
def test_int_text_round_trip_in_every_digit_script(n: int, script: str, thousands: bool) -> None:
    table = {"latin": "0123456789", "persian": "۰۱۲۳۴۵۶۷۸۹", "arabic": "٠١٢٣٤٥٦٧٨٩"}[script]
    text = f"{abs(n):,}" if thousands else str(abs(n))
    text = ("-" if n < 0 else "") + "".join(table[int(ch)] if ch.isdigit() else ch for ch in text)
    assert conv([text], to="int64")[0] == [n]
    assert conv(conv([text], to="int64")[0], pl.Int64, to="string")[0] == [str(n)]


def test_change_type_on_a_sheet_writes_numbers_and_undoes() -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("v")], [txt("۱٬۲۳۴")], [txt("5")], [None]])
    original = ctx.snapshot()
    op = Operation(type="change_type", target=SheetRangeTarget(range=ctx.rng(0, 0, 3, 0)),
                   params={"column": "v", "to": "int64"})
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "ok" and ctx.grid[(1, 0)].v == num(1234) and ctx.grid[(2, 0)].v == num(5)
    ctx.apply_delta(res.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original
    bad = ctx.snapshot()
    ctx.put(2, 0, txt("x"))
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "error" and res.errors[0].code == "type_mismatch" and ctx.writes == 1
    assert bad  # snapshot taken before the corrupting edit stays usable
