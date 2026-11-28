"""Data operations on messy, realistic data: Persian/English text, Arabic letter variants, mixed digit scripts,
numbers and dates stored as text, null keys, duplicate keys, huge ids. Each assertion is a concrete value."""
from __future__ import annotations

import datetime as dt
from typing import Any

import polars as pl
import pytest

from gridora_dataops.errors import DataOpsError
from gridora_dataops.registry import default_registry
from gridora_dataops.spec import PlanEnv

REG = default_registry()


def run(op: str, df: pl.DataFrame, extra: pl.DataFrame | None = None, **params: Any) -> tuple[list[dict[str, Any]], list[str]]:
    spec = REG.get(op)
    assert spec is not None
    p = spec.Params.model_validate(params)
    out = spec.plan(df, p, PlanEnv(has_header=True, column_names=df.columns, extra_frames=[extra] if extra is not None else []))
    return out.frame.to_dicts(), [w.code for w in out.warnings]


def fails(op: str, df: pl.DataFrame, extra: pl.DataFrame | None = None, **params: Any) -> DataOpsError:
    with pytest.raises(DataOpsError) as e:
        run(op, df, extra, **params)
    return e.value


# ------------------------------------------------------------------------------------------------ join
def test_join_keeps_long_integer_ids_apart_instead_of_merging_them_as_floats() -> None:
    left = pl.DataFrame({"id": [9007199254740993, 9007199254740992, 5], "v": ["a", "b", "c"]})  # 2^53 + 1, 2^53
    right = pl.DataFrame({"id": [9007199254740992], "w": ["X"]})
    rows, _ = run("join", left, right, how="left", left_on=["id"], right_on=["id"])
    assert [(r["v"], r["w"]) for r in rows] == [("a", None), ("b", "X"), ("c", None)]  # used to give "a" the X too


def test_join_integer_against_decimal_keys_warns_when_precision_cannot_be_kept() -> None:
    rows, warns = run("join", pl.DataFrame({"k": [2**60, 1]}), pl.DataFrame({"k": [1.0]}), how="left", left_on=["k"], right_on=["k"])
    assert len(rows) == 2 and warns == ["join_key_precision"]
    assert run("join", pl.DataFrame({"k": [1, 2]}), pl.DataFrame({"k": [1.0]}), how="inner", left_on=["k"], right_on=["k"]) == (
        [{"k": 1}], [])


def test_join_text_keys_can_ignore_spaces_case_and_arabic_letter_variants() -> None:
    left = pl.DataFrame({"city": ["Tehran ", " tehran", "Karaj", "كرج", None]})
    right = pl.DataFrame({"city": ["tehran", "Karaj", "کرج", None], "p": [1, 2, 3, 4]})
    strict, _ = run("join", left, right, how="left", left_on=["city"], right_on=["city"])
    assert [r["p"] for r in strict] == [None, None, 2, None, None]
    loose, _ = run("join", left, right, how="left", left_on=["city"], right_on=["city"], trim=True,
                   case_sensitive=False, ignore_variants=True)
    # the left keys keep their original spelling; a null key never matches a null key
    assert [(r["city"], r["p"]) for r in loose] == [("Tehran ", 1), (" tehran", 1), ("Karaj", 2), ("كرج", 3), (None, None)]


def test_join_null_duplicate_and_unmatched_keys() -> None:
    left = pl.DataFrame({"k": [1, None, 2, 2], "x": list("abcd")})
    right = pl.DataFrame({"k": [None, 2, 2, 3], "y": list("wxyz")})
    rows, _ = run("join", left, right, how="full", left_on=["k"], right_on=["k"])
    got = sorted((r["k"] if r["k"] is not None else -1, r["x"] or "-", r["y"] or "-") for r in rows)
    assert got == sorted([(1, "a", "-"), (-1, "b", "-"), (2, "c", "x"), (2, "c", "y"), (2, "d", "x"), (2, "d", "y"),
                          (-1, "-", "w"), (3, "-", "z")])  # 2 x 2 matches multiply; null keys stay unmatched on both sides
    assert len(run("join", left, right, how="inner", left_on=["k"], right_on=["k"])[0]) == 4


def test_join_refuses_a_suffix_that_would_create_a_duplicate_column_instead_of_crashing() -> None:
    e = fails("join", pl.DataFrame({"k": [1], "a": [1], "a_right": [2]}), pl.DataFrame({"k": [1], "a": [9]}),
              how="inner", left_on=["k"], right_on=["k"])
    assert (e.code, e.errors[0].path) == ("invalid_param", "/params/suffix")
    ok, _ = run("join", pl.DataFrame({"k": [1], "a": [1], "a_right": [2]}), pl.DataFrame({"k": [1], "a": [9]}),
                how="inner", left_on=["k"], right_on=["k"], suffix="_2")
    assert ok == [{"k": 1, "a": 1, "a_right": 2, "a_2": 9}]


# ------------------------------------------------------------------------------------------------ pivot / fill
def test_pivot_value_named_like_an_index_column_gets_a_unique_name() -> None:
    rows, _ = run("pivot", pl.DataFrame({"r": [1, 2], "c": ["r", "r"], "v": [1, 2]}), index=["r"], columns="c", values="v", fn="sum")
    assert rows == [{"r": 1, "r_2": 1}, {"r": 2, "r_2": 2}]
    rows, _ = run("pivot", pl.DataFrame({"r": [1], "s": ["q"], "c": ["s"], "v": [5]}), index=["r", "s"], columns="c", values="v", fn="count")
    assert rows == [{"r": 1, "s": "q", "s_2": 1}]


def test_pivot_sum_keeps_missing_combinations_empty_and_null_categories_visible() -> None:
    df = pl.DataFrame({"r": ["a", "a", "b", "b", None], "c": ["x", "y", "x", "x", None], "v": [1.0, 2.0, 3.0, 4.0, 5.0]})
    rows, _ = run("pivot", df, index=["r"], columns="c", values="v", fn="sum")
    assert rows == [{"r": "a", "x": 1.0, "y": 2.0, "(خالی)": None}, {"r": "b", "x": 7.0, "y": None, "(خالی)": None},
                    {"r": None, "x": None, "y": None, "(خالی)": 5.0}]


def test_fill_constant_on_all_columns_skips_the_ones_it_does_not_fit_and_says_so() -> None:
    df = pl.DataFrame({"a": ["x", "  ", None], "n": [1.0, None, 3.0], "b": [True, None, False]})
    rows, warns = run("fill", df, mode="constant", value=0)
    assert rows == [{"a": "x", "n": 1.0, "b": True}, {"a": "  ", "n": 0.0, "b": None}, {"a": None, "n": 3.0, "b": False}]
    assert warns == ["fill_skipped_columns"]


def test_fill_constant_on_a_chosen_column_that_cannot_take_it_names_the_column() -> None:
    e = fails("fill", pl.DataFrame({"a": ["x"], "n": [1.0]}), columns=["a", "n"], mode="constant", value="s")
    assert e.code == "type_mismatch" and "'n'" in e.message
    assert fails("fill", pl.DataFrame({"a": ["x"]}), mode="constant", value=1).errors[0].path == "/params/value"
    assert fails("fill", pl.DataFrame({"a": ["x"]}), mode="constant").errors[0].path == "/params/value"


def test_fill_down_treats_blank_text_as_empty_and_never_touches_filled_cells() -> None:
    rows, _ = run("fill", pl.DataFrame({"a": ["x", "  ", None, "y", ""]}), mode="down")
    assert [r["a"] for r in rows] == ["x", "x", "x", "y", "y"]


# ------------------------------------------------------------------------------------------------ change_type
def test_text_dates_that_are_really_jalali_are_never_stored_as_the_year_1403() -> None:
    df = pl.DataFrame({"d": ["2024-03-15", "۱۴۰۳/۰۱/۰۱", "1403-1-1", "2024/3/5", "2024-02-30", "", None]})
    rows, warns = run("change_type", df, column="d", to="date", on_error="null")
    assert [r["d"] for r in rows] == [dt.date(2024, 3, 15), None, None, dt.date(2024, 3, 5), None, None, None]
    assert warns == ["values_set_to_null", "dates_look_jalali"]
    e = fails("change_type", df, column="d", to="date", on_error="fail")
    assert e.code == "type_mismatch" and "2 look like Jalali dates" in (e.errors[0].hint or "")
    # the explicit, correct route reads them
    fixed, _ = run("convert_calendar", pl.DataFrame({"d": ["۱۴۰۳/۰۱/۰۱", "1403-1-1"]}), column="d", direction="from_jalali")
    assert [r["d"] for r in fixed] == [dt.date(2024, 3, 20), dt.date(2024, 3, 20)]


def test_numbers_become_text_the_way_a_person_reads_them() -> None:
    df = pl.DataFrame({"x": [0.1 + 0.2, 1e20, 2.5, 3.0, None, -4.0], "id": [1234567890123456, 6037991234567890, 5, 0, 1, 2]})
    assert [r["x"] for r in run("change_type", df, column="x", to="string")[0]] == ["0.3", "1e+20", "2.5", "3", None, "-4"]
    assert [r["id"] for r in run("change_type", df, column="id", to="string")[0]][:3] == ["1234567890123456", "6037991234567890", "5"]


def test_an_empty_boolean_cell_stays_empty_as_text() -> None:
    assert [r["b"] for r in run("change_type", pl.DataFrame({"b": [True, None, False]}), column="b", to="string")[0]] == ["true", None, "false"]


def test_text_numbers_in_every_script_and_the_ones_that_are_not_numbers() -> None:
    df = pl.DataFrame({"s": ["12", "۱۲٬۳۴۵", "1.5", "٣٫٥", "abc", "", "  7 ", "12 345", None, "$12"]})
    rows, warns = run("change_type", df, column="s", to="float64", on_error="null")
    assert [r["s"] for r in rows] == [12.0, 12345.0, 1.5, 3.5, None, None, 7.0, 12345.0, None, None]
    assert warns == ["values_set_to_null"]  # "abc" and "$12"; "" and null are empty, not errors
    assert fails("change_type", df, column="s", to="int64", on_error="fail").code == "type_mismatch"


# ------------------------------------------------------------------------------------------------ clean / dedupe / replace / split / sort
def test_cleaning_then_deduplicating_names_with_spaces_case_and_letter_variants() -> None:
    names = pl.DataFrame({"n": ["  علي   رضا ", "علی رضا", "Ali  Reza", "ali reza", None, None, "\tعلی\u00a0رضا"], "v": range(7)})
    cleaned, _ = run("clean_text", names, columns=["n"], arabic_letters_to_persian=True)
    assert [r["n"] for r in cleaned] == ["علی رضا", "علی رضا", "Ali Reza", "ali reza", None, None, "علی رضا"]
    deduped, _ = run("remove_duplicates", pl.DataFrame(cleaned), columns=["n"])
    # three spellings of the first name collapse; Ali/ali too (case-insensitive by default); empty cells count as one
    assert [(r["n"], r["v"]) for r in deduped] == [("علی رضا", 0), ("Ali Reza", 2), (None, 4)]


def test_dedupe_does_not_trim_by_itself_so_clean_first() -> None:
    rows, _ = run("remove_duplicates", pl.DataFrame({"n": ["علی", "علی ", "علي"]}), columns=["n"])
    assert len(rows) == 3
    assert len(run("remove_duplicates", pl.DataFrame({"n": ["علی", "علی ", "علي"]}), columns=["n"], ignore_variants=True)[0]) == 2


def test_find_replace_whole_or_part_case_variants_and_dollar_signs() -> None:
    df = pl.DataFrame({"t": ["Price: $5", "price", "كتاب", "کتاب‌ها", None, "5"]})
    first = run("find_replace", df, find="$5", replace="$$ 6")[0][0]["t"]
    assert first == "Price: $$ 6"  # "$" is text, in the needle and in the replacement
    assert [r["t"] for r in run("find_replace", df, find="price", replace="X", match="whole")[0]] == ["Price: $5", "X", "كتاب", "کتاب‌ها", None, "5"]
    assert [r["t"] for r in run("find_replace", df, find="کتاب", replace="Book", ignore_variants=True)[0]][2:4] == ["Book", "Book‌ها"]
    assert [r["t"] for r in run("find_replace", df, find="کتاب", replace="Book")[0]][2:4] == ["كتاب", "Book‌ها"]


def test_split_with_leading_delimiter_keeps_the_empty_first_part_like_a_spreadsheet() -> None:
    rows, _ = run("split_column", pl.DataFrame({"f": ["  x  y ", "علی رضا احمدی", None]}), column="f", mode="delimiter",
                  delimiter=" ", merge_delimiters=True, max_parts=3)
    assert rows == [{"f_1": None, "f_2": "x", "f_3": "y"}, {"f_1": "علی", "f_2": "رضا", "f_3": "احمدی"}, {"f_1": None, "f_2": None, "f_3": None}]


def test_sort_puts_persian_text_in_alphabet_order_and_empty_cells_last_both_ways() -> None:
    df = pl.DataFrame({"n": ["ب", "آ", "ا", "a", "B", "1", None, "ی"], "v": range(8)})
    asc = [r["n"] for r in run("sort", df, keys=[{"column": "n"}])[0]]
    assert asc == ["1", "a", "B", "آ", "ا", "ب", "ی", None]
    desc = [r["n"] for r in run("sort", df, keys=[{"column": "n", "direction": "desc"}])[0]]
    assert desc[:-1] == list(reversed(asc[:-1])) and desc[-1] is None


def test_group_aggregate_counts_empty_groups_and_merges_letter_variants() -> None:
    df = pl.DataFrame({"city": ["كرج", "کرج", None, None, "تهران"], "amt": [1.0, 2.0, 3.0, None, None]})
    rows, _ = run("group_aggregate", df, by=["city"], ignore_variants=True,
                  aggregations=[{"fn": "sum", "column": "amt"}, {"fn": "count", "column": "amt"}, {"fn": "count"}])
    assert rows == [{"city": "كرج", "sum_amt": 3.0, "count_amt": 2, "count": 2}, {"city": None, "sum_amt": 3.0, "count_amt": 1, "count": 2},
                    {"city": "تهران", "sum_amt": 0.0, "count_amt": 0, "count": 1}]
