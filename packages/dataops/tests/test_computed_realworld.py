"""Computed columns on messy, realistic data: Persian and English text, mixed digit scripts, numbers stored as text,
nulls, negatives, leap days. Every assertion is a concrete value a person would expect to see in the sheet."""
from __future__ import annotations

import datetime as dt
import typing

import polars as pl
import pytest
from gridora_contracts.models import Operation, SheetRangeTarget
from pydantic import ValidationError

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.computed_column import (
    FN_META,
    ComputedColumnOp,
    ComputedParams,
    Fn,
    function_catalog,
)
from gridora_dataops.spec import PlanEnv


def lit(v):  # type: ignore[no-untyped-def]
    return {"kind": "lit", "value": v}


def col(n):  # type: ignore[no-untyped-def]
    return {"kind": "col", "name": n}


def call(fn, *args):  # type: ignore[no-untyped-def]
    return {"kind": "call", "fn": fn, "args": list(args)}


def comp(df: pl.DataFrame, expr, name="r"):  # type: ignore[no-untyped-def]
    out = ComputedColumnOp().plan(df, ComputedParams.model_validate({"name": name, "expr": expr}), PlanEnv())
    return out.frame[name].to_list(), out


def fails(df: pl.DataFrame, expr):  # type: ignore[no-untyped-def]
    with pytest.raises(DataOpsError) as e:
        comp(df, expr)
    return e.value.errors[0]


PRICES = pl.DataFrame({"price": ["۱٬۲۰۰", "1,234.5", "  ۵ ", "٣٫٥", "abc", "", None, "-7", "1e3x"]})


# ------------------------------------------------------------------ numbers stored as text
def test_to_number_reads_every_digit_script_and_separator_and_warns_about_the_rest() -> None:
    values, out = comp(PRICES, call("to_number", col("price")))
    assert values == [1200.0, 1234.5, 5.0, 3.5, None, None, None, -7.0, None]
    # "abc" and "1e3x" are not numbers; "" and null are simply empty, so they are not counted
    assert [(w.code, w.message.split()[0]) for w in out.warnings] == [("number_parse_failed", "2")]


def test_to_number_with_a_comma_decimal_separator() -> None:
    df = pl.DataFrame({"v": ["1.234,5", "۱۲٫۵", "0,25"]})
    assert comp(df, call("to_number", col("v"), lit(",")))[0] == [1234.5, 12.5, 0.25]
    assert fails(df, call("to_number", col("v"), lit(";"))).path == "/params/expr/args/1"
    assert fails(df, call("to_number", col("v"), col("v"))).path == "/params/expr/args/1"


def test_to_number_only_takes_text_and_feeds_arithmetic() -> None:
    assert fails(pl.DataFrame({"n": [1.0]}), call("to_number", col("n"))).code == "type_mismatch"
    total = call("mul", call("to_number", col("price")), lit(2))
    assert comp(PRICES, total)[0] == [2400.0, 2469.0, 10.0, 7.0, None, None, None, -14.0, None]


def test_to_text_gives_whole_numbers_without_a_decimal_point_and_no_float_noise() -> None:
    df = pl.DataFrame({"x": [3.0, 0.1, 2.5, -4.0, None, 1e20], "b": [True, False, None, True, False, True]})
    assert comp(df, call("to_text", col("x")))[0] == ["3", "0.1", "2.5", "-4", None, "1e+20"]
    assert comp(df, call("to_text", call("add", lit(0.1), lit(0.2))))[0] == ["0.3"] * 6
    assert comp(df, call("to_text", col("b")))[0] == ["true", "false", None, "true", "false", "true"]
    assert comp(df, call("concat", call("add", lit(0.1), lit(0.2)), lit("-"), col("x")))[0][1] == "0.3-0.1"


# ------------------------------------------------------------------ rounding
def test_round_goes_half_away_from_zero_like_a_spreadsheet_not_to_even() -> None:
    df = pl.DataFrame({"x": [2.5, -2.5, 0.5, 1.5, -0.5, 3.4, None]})
    assert comp(df, call("round", col("x")))[0] == [3.0, -3.0, 1.0, 2.0, -1.0, 3.0, None]


def test_round_with_digits() -> None:
    df = pl.DataFrame({"x": [2.675, 0.125, -1.236, 1234.5678]})
    assert comp(df, call("round", col("x"), lit(2)))[0] == [2.68, 0.13, -1.24, 1234.57]
    assert comp(df, call("round", col("x"), lit(0)))[0] == [3.0, 0.0, -1.0, 1235.0]
    for bad in (lit(16), lit(-1), lit(1.5), col("x"), lit("2")):
        assert fails(df, call("round", col("x"), bad)).path == "/params/expr/args/1"


# ------------------------------------------------------------------ text extraction that used to crash
def test_negative_counts_give_empty_text_instead_of_crashing_the_run() -> None:
    df = pl.DataFrame({"s": ["abc", "علی رضا", None], "n": [-1, -5, 2]})
    assert comp(df, call("left", col("s"), col("n")))[0] == ["", "", None]
    assert comp(df, call("right", col("s"), col("n")))[0] == ["", "", None]
    assert comp(df, call("substring", col("s"), lit(1), col("n")))[0] == ["", "", None]
    assert comp(df, call("substring", col("s"), lit(-3), lit(2)))[0] == ["ab", "عل", None]  # start before 1 counts as 1


# ------------------------------------------------------------------ Persian text
def test_fold_makes_arabic_and_persian_spellings_compare_equal() -> None:
    df = pl.DataFrame({"a": ["كتاب ۱۲۳", "کتاب 123", "عليرضا", "علیرضا", None], "b": ["کتاب 123"] * 2 + ["علیرضا"] * 2 + ["x"]})
    same = call("eq", call("fold", col("a")), call("fold", col("b")))
    assert comp(df, same)[0] == [True, True, True, True, None]
    assert comp(df, call("eq", col("a"), col("b")))[0] == [False, True, False, True, None]  # without fold they differ


def test_contains_starts_ends_with_and_nulls() -> None:
    df = pl.DataFrame({"s": ["تهران - ونک", "کرج", "", None, "a.b"]})
    assert comp(df, call("contains", col("s"), lit("ونک")))[0] == [True, False, False, None, False]
    assert comp(df, call("starts_with", col("s"), lit("ته")))[0] == [True, False, False, None, False]
    assert comp(df, call("ends_with", col("s"), lit(".b")))[0] == [False, False, False, None, True]
    assert comp(df, call("contains", col("s"), lit(".")))[0] == [False, False, False, None, True]  # literal, not a regex
    assert comp(df, call("contains", col("s"), lit("")))[0] == [True, True, True, None, True]


# ------------------------------------------------------------------ mapping and classification
CITIES = pl.DataFrame({"code": ["THR", "KRJ", "thr", None, "XXX"], "score": [95.0, 70.0, 50.0, None, 85.0]})


def test_switch_maps_values_with_and_without_a_default() -> None:
    mapping = ["THR", "تهران", "KRJ", "کرج"]
    assert comp(CITIES, call("switch", col("code"), *map(lit, mapping)))[0] == ["تهران", "کرج", None, None, None]
    assert comp(CITIES, call("switch", col("code"), *map(lit, mapping), lit("نامشخص")))[0] == [
        "تهران", "کرج", "نامشخص", "نامشخص", "نامشخص"]
    # normalise first, then map: the usual way to cope with inconsistent capitalisation
    assert comp(CITIES, call("switch", call("upper", col("code")), *map(lit, mapping), lit("-")))[0] == [
        "تهران", "کرج", "تهران", "-", "-"]


def test_switch_type_and_shape_errors() -> None:
    assert fails(CITIES, call("switch", col("code"), lit(1), lit("x"))).code == "type_mismatch"          # key type
    assert fails(CITIES, call("switch", col("code"), lit("A"), lit(1), lit("B"), lit("x"))).code == "type_mismatch"  # results
    assert fails(CITIES, call("switch", col("code"), lit("A"))).path == "/params/expr/args"


def test_between_is_inclusive_and_classification_nests_with_if() -> None:
    assert comp(CITIES, call("between", col("score"), lit(70), lit(90)))[0] == [False, True, False, None, True]
    grade = call("if", call("ge", col("score"), lit(90)), lit("A"),
                 call("if", call("between", col("score"), lit(70), lit(89.99)), lit("B"), lit("C")))
    # a missing score is not a pass: the null test falls through to the else branch, like a spreadsheet's IF
    assert comp(CITIES, grade)[0] == ["A", "B", "C", "C", "B"]


# ------------------------------------------------------------------ dates
DATES = pl.DataFrame({
    "start": [dt.date(2024, 2, 28), dt.date(2023, 12, 31), None, dt.date(2024, 3, 1)],
    "end": [dt.date(2024, 3, 1), dt.date(2023, 1, 1), dt.date(2024, 1, 1), dt.date(2024, 3, 1)],
})


def test_days_between_counts_calendar_days_signed_and_across_a_leap_day() -> None:
    assert comp(DATES, call("days_between", col("start"), col("end")))[0] == [2.0, -364.0, None, 0.0]


def test_add_days_crosses_months_and_years_and_keeps_the_type() -> None:
    values, _ = comp(DATES, call("add_days", col("start"), lit(2)))
    assert values == [dt.date(2024, 3, 1), dt.date(2024, 1, 2), None, dt.date(2024, 3, 3)]
    assert comp(DATES, call("add_days", col("end"), lit(-1)))[0][1] == dt.date(2022, 12, 31)
    assert fails(DATES, call("add_days", lit("2024-01-01"), lit(1))).code == "type_mismatch"
    assert fails(DATES, call("days_between", col("start"), lit(3))).code == "type_mismatch"


# ------------------------------------------------------------------ limits and safety
def test_a_number_that_floats_cannot_hold_is_refused_instead_of_silently_changed() -> None:
    with pytest.raises(ValidationError):
        ComputedParams.model_validate({"name": "r", "expr": lit(2**60 + 1)})
    assert ComputedParams.model_validate({"name": "r", "expr": lit(2**53)}).expr.value == 2.0**53


def test_switch_accepts_the_largest_argument_list_and_not_one_more() -> None:
    ok = call("switch", col("code"), *[lit(str(i)) for i in range(18)], lit("d"))  # value + 9 pairs + default = 20
    assert len(comp(CITIES, ok)[0]) == 5
    with pytest.raises(ValidationError):
        ComputedParams.model_validate({"name": "r", "expr": call("switch", col("code"), *[lit(str(i)) for i in range(21)])})


def test_every_function_has_catalog_metadata_and_the_schema_carries_it() -> None:
    assert set(FN_META) == set(typing.get_args(Fn))
    for fn, (category, signature, returns) in FN_META.items():
        assert signature.startswith(fn + "("), fn
        assert category in {"math", "text", "logic", "date", "convert"} and returns in {"num", "text", "bool", "date", "any"}
    schema = ComputedColumnOp().descriptor().params_schema
    assert schema["properties"]["expr"]["x-gridora-functions"] == function_catalog()


# ------------------------------------------------------------------ preview == apply on a sheet
def test_a_text_number_column_previews_exactly_what_applying_writes() -> None:
    from fakes import FakeExecContext, txt

    ctx = FakeExecContext()
    ctx.fill([[txt("price")], [txt("۱٬۲۰۰")], [txt("1,234.5")], [txt("abc")], [txt("")]])
    op = Operation(type="computed_column", target=SheetRangeTarget(range=ctx.rng(0, 0, 4, 0)),
                   params={"name": "n", "expr": call("to_number", col("price"))})
    ex = DataOpsExecutor()
    assert ex.validate(op, ctx) == []
    preview = ex.preview(op, ctx, 100)
    assert preview.columns == ["price", "n"] and [r[1] for r in preview.rows] == [1200.0, 1234.5, None, None]
    assert [w.code for w in preview.warnings] == ["number_parse_failed"]
    res = ex.apply(op, ctx)
    assert res.status == "ok" and [w.code for w in res.warnings] == ["number_parse_failed"]
    written = [ctx.grid.get((r, 1)) for r in range(1, 5)]
    assert [getattr(c.v, "n", None) if c else None for c in written][:2] == [1200.0, 1234.5]
