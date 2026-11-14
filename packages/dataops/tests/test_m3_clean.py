from __future__ import annotations

import polars as pl
import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import Operation, SheetRangeTarget
from hypothesis import given, settings
from hypothesis import strategies as st

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.clean_text import CleanTextOp, CleanTextParams
from gridora_dataops.ops.fill import FillOp, FillParams
from gridora_dataops.ops.find_replace import FindReplaceOp, FindReplaceParams
from gridora_dataops.ops.merge_columns import MergeColumnsOp, MergeParams
from gridora_dataops.ops.split_column import SplitColumnOp, SplitParams
from gridora_dataops.spec import PlanEnv

ENV = PlanEnv()


def run_op(spec, params_cls, df, **p):  # type: ignore[no-untyped-def]
    return spec.plan(df, params_cls.model_validate(p), ENV)


def fr(df: pl.DataFrame, **p) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    return run_op(FindReplaceOp(), FindReplaceParams, df, **p).frame


def ct(df: pl.DataFrame, **p) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    return run_op(CleanTextOp(), CleanTextParams, df, **p).frame


# ------------------------------------------------------------ find_replace
def test_find_replace_partial_is_case_insensitive_by_default_and_literal() -> None:
    df = pl.DataFrame({"a": ["Hello.World", "hello world", None], "n": [1, 2, 3]})
    assert fr(df, find="hello", replace="X")["a"].to_list() == ["X.World", "X world", None]
    assert fr(df, find="hello", replace="X", case_sensitive=True)["a"].to_list() == ["Hello.World", "X world", None]
    assert fr(df, find=".", replace="-")["a"].to_list() == ["Hello-World", "hello world", None]  # not a regex
    assert fr(df, find="o", replace="$1")["a"].to_list()[1] == "hell$1 w$1rld"                    # $ is literal


def test_find_replace_whole_cell() -> None:
    df = pl.DataFrame({"a": ["x", "xx", "X", " x"]})
    assert fr(df, find="x", replace="Y", match="whole")["a"].to_list() == ["Y", "xx", "Y", " x"]


def test_find_replace_variants_keep_the_rest_of_the_text_untouched() -> None:
    df = pl.DataFrame({"a": ["كتاب ۱۲۳ ياد", "کتاب 123 یاد"]})
    assert fr(df, find="کتاب", replace="X")["a"].to_list() == ["كتاب ۱۲۳ ياد", "X 123 یاد"]
    assert fr(df, find="کتاب", replace="X", ignore_variants=True)["a"].to_list() == ["X ۱۲۳ ياد", "X 123 یاد"]
    assert fr(df, find="123", replace="#", ignore_variants=True)["a"].to_list() == ["كتاب # ياد", "کتاب # یاد"]
    assert fr(pl.DataFrame({"a": ["کتـاب"]}), find="کتاب", replace="X", ignore_variants=True)["a"].to_list() == ["X"]


def test_find_replace_columns_selection_and_type_errors() -> None:
    df = pl.DataFrame({"a": ["x"], "b": ["x"], "n": [1]})
    assert fr(df, find="x", replace="y", columns=["b"]).rows() == [("x", "y", 1)]
    with pytest.raises(DataOpsError) as e:
        fr(df, find="x", columns=["a", "n"])
    assert (e.value.code, e.value.errors[0].path) == ("type_mismatch", "/params/columns/1")


# ------------------------------------------------------------ fill
def fl(df: pl.DataFrame, **p) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    return run_op(FillOp(), FillParams, df, **p).frame


def test_fill_down_up_and_blank_text_counts_as_empty() -> None:
    df = pl.DataFrame({"a": [None, "x", "  ", None, "y", None]})
    assert fl(df, mode="down")["a"].to_list() == [None, "x", "x", "x", "y", "y"]
    assert fl(df, mode="up")["a"].to_list() == ["x", "x", "y", "y", "y", None]


def test_fill_constant_is_typed() -> None:
    df = pl.DataFrame({"s": [None, "a"], "n": [None, 2.0]})
    assert fl(df, mode="constant", columns=["s"], value="-")["s"].to_list() == ["-", "a"]
    assert fl(df, mode="constant", columns=["n"], value=0)["n"].to_list() == [0.0, 2.0]
    with pytest.raises(DataOpsError) as e:
        fl(df, mode="constant", columns=["n"], value="text")
    assert (e.value.code, e.value.errors[0].path) == ("type_mismatch", "/params/value")
    with pytest.raises(DataOpsError):
        fl(df, mode="constant")


@settings(max_examples=60, deadline=None)
@given(st.lists(st.one_of(st.none(), st.integers(-3, 3)), max_size=25), st.sampled_from(["down", "up", "constant"]))
def test_fill_never_changes_a_non_empty_cell_and_is_idempotent(vals, mode) -> None:  # type: ignore[no-untyped-def]
    df = pl.DataFrame({"a": vals}, schema={"a": pl.Int64})
    out = fl(df, mode=mode, value=9)
    assert all(o == v for o, v in zip(out["a"], vals, strict=True) if v is not None)
    assert fl(out, mode=mode, value=9).equals(out)


# ------------------------------------------------------------ clean_text
def test_clean_text_whitespace_defaults() -> None:
    df = pl.DataFrame({"a": ["  a   b\u00a0c  ", None, ""], "n": [1, 2, 3]})
    assert ct(df)["a"].to_list() == ["a b c", None, ""]


def test_clean_text_persian_options_are_off_by_default() -> None:
    df = pl.DataFrame({"a": ["كتاب ۱۲۳ ـ"]})
    assert ct(df)["a"].to_list() == ["كتاب ۱۲۳ ـ"]
    assert ct(df, arabic_letters_to_persian=True, digits="to_latin", remove_tatweel=True)["a"].to_list() == ["کتاب 123"]


@pytest.mark.parametrize(("digits", "expected"), [("to_latin", "0123456789"), ("to_persian", "۰۱۲۳۴۵۶۷۸۹"),
                                                  ("to_arabic_indic", "٠١٢٣٤٥٦٧٨٩")])
def test_clean_text_digit_scripts(digits: str, expected: str) -> None:
    df = pl.DataFrame({"a": ["0123456789", "۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩"]})
    assert ct(df, digits=digits)["a"].to_list() == [expected] * 3


def test_clean_text_zwnj_and_diacritics_and_case() -> None:
    df = pl.DataFrame({"a": ["می\u200cخواهم", "کِتاب", "hello wORLD"]})
    assert ct(df, zwnj="remove")["a"].to_list()[0] == "میخواهم"
    assert ct(df, zwnj="to_space")["a"].to_list()[0] == "می خواهم"
    assert ct(df)["a"].to_list()[0] == "می\u200cخواهم"  # kept by default
    assert ct(df, remove_diacritics=True)["a"].to_list()[1] == "کتاب"
    assert ct(df, case="title")["a"].to_list()[2] == "Hello World"
    assert ct(df, case="upper")["a"].to_list()[2] == "HELLO WORLD"


def test_clean_text_skips_non_text_columns_unless_named() -> None:
    df = pl.DataFrame({"a": [" x "], "n": [1]})
    assert ct(df).rows() == [("x", 1)]
    with pytest.raises(DataOpsError):
        ct(df, columns=["n"])


@settings(max_examples=80, deadline=None)
@given(st.text(alphabet="ابپ يكی۱٢3a Bـ\u200c\u00a0.", max_size=12),
       st.sampled_from(["none", "to_latin", "to_persian", "to_arabic_indic"]), st.booleans(), st.sampled_from(["keep", "remove", "to_space"]))
def test_clean_text_is_idempotent(text, digits, arabic, zwnj) -> None:  # type: ignore[no-untyped-def]
    df = pl.DataFrame({"a": [text]})
    kw = {"digits": digits, "arabic_letters_to_persian": arabic, "zwnj": zwnj, "remove_tatweel": True,
          "remove_diacritics": True, "case": "lower"}
    once = ct(df, **kw)
    assert ct(once, **kw).equals(once)


# ------------------------------------------------------------ split_column
def sp(df: pl.DataFrame, **p) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    return run_op(SplitColumnOp(), SplitParams, df, **p).frame


def test_split_by_delimiter_names_positions_and_blanks() -> None:
    df = pl.DataFrame({"x": ["a,b,c", "d, e", None, "f,,g"], "k": [1, 2, 3, 4]})
    out = sp(df, column="x")
    assert out.columns == ["x_1", "x_2", "x_3", "k"]
    assert out.rows() == [("a", "b", "c", 1), ("d", "e", None, 2), (None, None, None, 3), ("f", None, "g", 4)]
    assert sp(df, column="x", keep_source=True).columns == ["x", "x_1", "x_2", "x_3", "k"]


def test_split_max_parts_keeps_the_rest_in_the_last_column() -> None:
    df = pl.DataFrame({"x": ["a b c d", "e f", "g"]})
    assert sp(df, column="x", delimiter=" ", max_parts=2).rows() == [("a", "b c d"), ("e", "f"), ("g", None)]


def test_split_merge_delimiters_and_persian_text() -> None:
    df = pl.DataFrame({"x": ["علی   رضایی", "سارا احمدی"]})
    assert sp(df, column="x", delimiter=" ", merge_delimiters=True).rows() == [("علی", "رضایی"), ("سارا", "احمدی")]


def test_split_fixed_width_and_name_collisions() -> None:
    df = pl.DataFrame({"x": ["abcdef", "gh"], "x_1": [1, 2]})
    out = sp(df, column="x", mode="fixed_width", widths=[2, 3])
    assert out.columns == ["x_1_2", "x_2", "x_1"] or out.columns[0].startswith("x_1")
    assert len(set(out.columns)) == len(out.columns) and out.rows()[0][:2] == ("ab", "cde")


def test_split_validation() -> None:
    op = SplitColumnOp()
    assert op.validate_static(SplitParams.model_validate({"column": "x", "delimiter": ""}))[0].path == "/params/delimiter"
    assert op.validate_static(SplitParams.model_validate({"column": "x", "mode": "fixed_width"}))[0].path == "/params/widths"
    with pytest.raises(DataOpsError):
        sp(pl.DataFrame({"x": [1]}), column="x")


# ------------------------------------------------------------ merge_columns
def mg(df: pl.DataFrame, **p) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    return run_op(MergeColumnsOp(), MergeParams, df, **p).frame


def test_merge_skips_empty_formats_numbers_and_places_the_column() -> None:
    df = pl.DataFrame({"a": ["علی", None, "x"], "b": ["", "رضایی", "y"], "n": [3.0, 1.5, None], "z": [1, 2, 3]})
    out = mg(df, columns=["a", "b", "n"], separator="-", output_name="m")
    assert out.columns == ["a", "b", "n", "m", "z"]
    assert out["m"].to_list() == ["علی-3", "رضایی-1.5", "x-y"]
    assert mg(df, columns=["a", "b"], skip_empty=False, separator="|", output_name="m")["m"].to_list() == ["علی|", "|رضایی", "x|y"]


def test_merge_replace_sources_and_unique_output_name() -> None:
    df = pl.DataFrame({"a": ["1"], "b": ["2"], "c": ["3"]})
    assert mg(df, columns=["a", "b"], keep_sources=False, output_name="m").columns == ["m", "c"]
    assert mg(df, columns=["a", "b"], output_name="c").columns == ["a", "b", "c_2", "c"]
    assert MergeColumnsOp().validate_static(MergeParams.model_validate({"columns": ["a", "a"]}))[0].code == "invalid_param"


def test_merge_all_empty_is_empty() -> None:
    assert mg(pl.DataFrame({"a": [None], "b": [""]}, schema={"a": pl.String, "b": pl.String}),
              columns=["a", "b"])["merged"].to_list() == [None]


# ------------------------------------------------------------ on a sheet, with undo
def sheet() -> FakeExecContext:
    ctx = FakeExecContext()
    ctx.fill([[txt("نام"), txt("شهر")], [txt("علی رضایی"), txt("كرج")], [txt("سارا  احمدی"), None]])
    return ctx


def run(type_: str, ctx: FakeExecContext, c1: int = 1, r1: int = 2, **params):  # type: ignore[no-untyped-def]
    return Operation(type=type_, target=SheetRangeTarget(range=ctx.rng(0, 0, r1, c1)), params=params)


def test_find_replace_on_a_sheet_undoes() -> None:
    ctx, ex = sheet(), DataOpsExecutor()
    original = ctx.snapshot()
    res = ex.apply(run("find_replace", ctx, find="كرج", replace="کرج", ignore_variants=True), ctx)
    assert res.status == "ok" and ctx.grid[(1, 1)].v == txt("کرج")
    ctx.apply_delta(res.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original


def test_split_on_a_sheet_needs_free_space_to_the_right() -> None:
    ctx, ex = sheet(), DataOpsExecutor()
    res = ex.apply(run("split_column", ctx, column="نام", delimiter=" ", merge_delimiters=True), ctx)
    assert res.status == "ok"  # result is 3 columns wide: نام_1, نام_2, شهر -> column C was free
    assert ctx.grid[(1, 0)].v == txt("علی") and ctx.grid[(1, 1)].v == txt("رضایی") and ctx.grid[(1, 2)].v == txt("كرج")
    ctx2 = sheet()
    ctx2.put(0, 2, txt("data"))
    res = ex.apply(run("split_column", ctx2, column="نام", delimiter=" ", merge_delimiters=True), ctx2)
    assert res.status == "error" and res.errors[0].code == "would_overwrite" and ctx2.writes == 0


def test_clean_and_fill_and_merge_on_a_sheet() -> None:
    ctx, ex = sheet(), DataOpsExecutor()
    assert ex.apply(run("clean_text", ctx, arabic_letters_to_persian=True), ctx).status == "ok"
    assert ctx.grid[(2, 0)].v == txt("سارا احمدی") and ctx.grid[(1, 1)].v == txt("کرج")
    assert ex.apply(run("fill", ctx, columns=["شهر"], mode="constant", value="نامشخص"), ctx).status == "ok"
    assert ctx.grid[(2, 1)].v == txt("نامشخص")
    res = ex.apply(run("merge_columns", ctx, columns=["نام", "شهر"], separator=" - ", output_name="کامل"), ctx)
    assert res.status == "ok"  # grows by one column into free space (column C)
    assert ctx.grid[(0, 2)].v == txt("کامل") and ctx.grid[(1, 2)].v == txt("علی رضایی - کرج")
    assert ctx.grid[(2, 2)].v == txt("سارا احمدی - نامشخص")
    assert num(1)  # keep import used
