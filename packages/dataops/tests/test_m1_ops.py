from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import polars as pl
import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import Operation, SheetRangeTarget
from hypothesis import given, settings
from hypothesis import strategies as st

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.filter import FilterOp, FilterParams
from gridora_dataops.ops.remove_duplicates import DedupeParams, RemoveDuplicatesOp
from gridora_dataops.ops.sort import SortOp, SortParams
from gridora_dataops.persian.chars import collation_key, variant_fold
from gridora_dataops.registry import default_registry
from gridora_dataops.spec import PlanEnv

ENV = PlanEnv()
GOLDEN = Path(__file__).parent / "golden"


def sort_plan(df: pl.DataFrame, keys: list[dict], **kw) -> pl.DataFrame:  # type: ignore[type-arg]
    return SortOp().plan(df, SortParams.model_validate({"keys": keys, **kw}), ENV).frame


def dedupe_plan(df: pl.DataFrame, **kw) -> pl.DataFrame:  # type: ignore[no-untyped-def]
    return RemoveDuplicatesOp().plan(df, DedupeParams.model_validate(kw), ENV).frame


def filter_plan(df: pl.DataFrame, where: dict) -> pl.DataFrame:  # type: ignore[type-arg]
    return FilterOp().plan(df, FilterParams.model_validate({"where": where}), ENV).frame


def cond(column: str, op: str, value=None, **kw) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return {"kind": "condition", "column": column, "op": op, "value": value, **kw}


# ------------------------------------------------------------ registry / golden schemas
def test_production_registry_ships_the_current_operations() -> None:
    assert [s.type for s in default_registry().all()] == ["change_type", "filter", "remove_duplicates", "sort"]


@pytest.mark.parametrize("spec", default_registry().all(), ids=lambda s: s.type)
def test_flags_match_the_operations_catalog(spec) -> None:  # type: ignore[no-untyped-def]
    catalog = {"sort": (False, True), "filter": (False, True), "remove_duplicates": (True, True), "change_type": (True, True)}
    assert (spec.destructive, spec.supports_preview) == catalog[spec.type]


@pytest.mark.parametrize("desc", DataOpsExecutor().describe_all(), ids=lambda d: d.type)
def test_golden_params_schema(desc) -> None:  # type: ignore[no-untyped-def]
    """The generated schema is normative (docs/PARAMS_SCHEMA.md). Update intentionally: UPDATE_GOLDEN=1 pytest."""
    path = GOLDEN / f"{desc.type}.schema.json"
    text = json.dumps(desc.params_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text


def test_production_descriptors_have_persian_text_for_every_key() -> None:
    from gridora_dataops import catalog
    from gridora_dataops.schema import required_i18n_keys
    fa = catalog("fa")
    for d in DataOpsExecutor().describe_all():
        assert [k for k in required_i18n_keys(d) if not fa.get(k, "").strip()] == [], d.type


# ------------------------------------------------------------ persian collation
PERSIAN_SORTED = ["آب", "ابر", "باران", "پدر", "تو", "جان", "چای", "حال", "خانه", "دوست", "رود", "زمین", "ژاله",
                  "سنگ", "شب", "صبح", "ضرب", "طلا", "ظهر", "عشق", "غروب", "فرزند", "قلم", "کتاب", "گل", "لب",
                  "ماه", "نان", "وقت", "هوا", "یار"]


def test_persian_alphabetical_order() -> None:
    shuffled = PERSIAN_SORTED[::-1]
    out = sort_plan(pl.DataFrame({"w": shuffled}), [{"column": "w"}])
    assert out["w"].to_list() == PERSIAN_SORTED


def test_binary_collation_differs_from_persian() -> None:
    df = pl.DataFrame({"w": ["لب", "گل"]})
    assert sort_plan(df, [{"column": "w"}])["w"].to_list() == ["گل", "لب"]            # گ before ل
    assert sort_plan(df, [{"column": "w"}], collation="binary")["w"].to_list() == ["لب", "گل"]  # code points


def test_arabic_variants_and_ignorables_tie_and_keep_original_order() -> None:
    words = ["كتاب", "کتاب", "كِتاب", "کتـاب", "کتا‌ب"]  # Arabic kaf, Persian kaf, with kasra, tatweel, ZWNJ
    out = sort_plan(pl.DataFrame({"w": words, "i": range(5)}), [{"column": "w"}])
    assert out["i"].to_list() == [0, 1, 2, 3, 4]


def test_class_order_symbols_digits_latin_persian() -> None:
    words = ["ب", "b", "B", "۲", "10", "-", " ", "a"]
    out = sort_plan(pl.DataFrame({"w": words}), [{"column": "w"}])["w"].to_list()
    assert out == [" ", "-", "10", "۲", "a", "b", "B", "ب"]


def test_collation_key_digits_are_equal_across_scripts() -> None:
    k = pl.DataFrame({"w": ["1", "۱", "١"]}).select(collation_key(pl.col("w")).alias("k"))["k"].to_list()
    assert len(set(k)) == 1


# ------------------------------------------------------------ sort behaviour
def test_sort_desc_nulls_and_stability() -> None:
    df = pl.DataFrame({"a": [2.0, None, 1.0, 2.0, None], "i": [0, 1, 2, 3, 4]})
    assert sort_plan(df, [{"column": "a"}])["i"].to_list() == [2, 0, 3, 1, 4]                       # nulls last
    assert sort_plan(df, [{"column": "a", "nulls": "first"}])["i"].to_list() == [1, 4, 2, 0, 3]
    assert sort_plan(df, [{"column": "a", "direction": "desc"}])["i"].to_list() == [0, 3, 2, 1, 4]  # ties keep order


def test_sort_multi_key() -> None:
    df = pl.DataFrame({"g": ["ب", "الف", "ب", "الف"], "n": [1.0, 2.0, 3.0, 1.0]})
    out = sort_plan(df, [{"column": "g"}, {"column": "n", "direction": "desc"}])
    assert out.rows() == [("الف", 2.0), ("الف", 1.0), ("ب", 3.0), ("ب", 1.0)]


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.one_of(st.none(), st.integers(-5, 5)), st.text(alphabet="abcآابپ۱2 ", max_size=4)), max_size=30))
def test_sort_is_idempotent_stable_and_a_permutation(rows) -> None:  # type: ignore[no-untyped-def]
    df = pl.DataFrame({"n": [r[0] for r in rows], "s": [r[1] for r in rows], "i": list(range(len(rows)))},
                      schema={"n": pl.Int64, "s": pl.String, "i": pl.Int64})
    keys = [{"column": "s"}, {"column": "n", "direction": "desc"}]
    once = sort_plan(df, keys)
    assert sorted(once["i"].to_list()) == list(range(len(rows)))
    assert sort_plan(once, keys).equals(once)
    # stability: rows with identical keys keep their original relative order
    groups: dict = {}  # type: ignore[type-arg]
    for n, s, i in once.select("n", "s", "i").rows():
        groups.setdefault((n, s), []).append(i)
    assert all(g == sorted(g) for g in groups.values())


# ------------------------------------------------------------ remove_duplicates
def test_dedupe_keep_first_last_and_subset() -> None:
    df = pl.DataFrame({"k": ["a", "b", "a", "c", "b"], "v": [1, 2, 3, 4, 5]})
    assert dedupe_plan(df, columns=["k"])["v"].to_list() == [1, 2, 4]
    assert dedupe_plan(df, columns=["k"], keep="last")["v"].to_list() == [3, 4, 5]
    assert dedupe_plan(df)["v"].to_list() == [1, 2, 3, 4, 5]  # all columns: nothing duplicated


def test_dedupe_case_and_variants_options() -> None:
    df = pl.DataFrame({"k": ["Ali", "ali", "كتاب", "کتاب", "۱۲", "12"]})
    assert dedupe_plan(df)["k"].to_list() == ["Ali", "كتاب", "کتاب", "۱۲", "12"]            # case-insensitive by default
    assert dedupe_plan(df, case_sensitive=True)["k"].len() == 6
    assert dedupe_plan(df, ignore_variants=True)["k"].to_list() == ["Ali", "كتاب", "۱۲"]


def test_dedupe_treats_nulls_as_equal() -> None:
    df = pl.DataFrame({"k": [None, "a", None]}, schema={"k": pl.String})
    assert dedupe_plan(df, columns=["k"]).height == 2


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 3), st.integers(0, 3)), max_size=30), st.sampled_from(["first", "last"]))
def test_dedupe_idempotent_and_keeps_expected_row(rows, keep) -> None:  # type: ignore[no-untyped-def]
    df = pl.DataFrame({"a": [r[0] for r in rows], "b": [r[1] for r in rows], "i": list(range(len(rows)))},
                      schema={"a": pl.Int64, "b": pl.Int64, "i": pl.Int64})
    out = dedupe_plan(df, columns=["a", "b"], keep=keep)
    assert dedupe_plan(out, columns=["a", "b"], keep=keep).equals(out)
    assert out.select("a", "b").unique().height == out.height
    expected = {}
    for a, b, i in df.rows():
        if keep == "first":
            expected.setdefault((a, b), i)
        else:
            expected[(a, b)] = i
    assert sorted(out["i"].to_list()) == sorted(expected.values())


# ------------------------------------------------------------ filter
DF = pl.DataFrame({
    "name": ["Ali", "سارا", None, "كتاب", "  "],
    "n": [1.0, 5.0, 10.0, None, 7.0],
    "d": [dt.date(2024, 1, 1), dt.date(2024, 6, 1), None, dt.date(2025, 1, 1), dt.date(2023, 1, 1)],
    "ok": [True, False, True, None, True],
    "i": [0, 1, 2, 3, 4],
})


@pytest.mark.parametrize(("where", "expected"), [
    (cond("n", "gt", 5), [2, 4]),
    (cond("n", "between", 5, value2=10), [1, 2, 4]),
    (cond("n", "ne", 5), [0, 2, 3, 4]),                       # blanks are included in "not equal"
    (cond("name", "eq", "ali"), [0]),                          # case-insensitive by default
    (cond("name", "eq", "ali", case_sensitive=True), []),
    (cond("name", "contains", "ا"), [1, 3]),
    (cond("name", "contains", "کتاب"), []),                    # Arabic kaf does not match Persian kaf ...
    (cond("name", "contains", "کتاب", ignore_variants=True), [3]),  # ... unless asked to
    (cond("name", "starts_with", "ال"), []),
    (cond("name", "not_contains", "ali"), [1, 2, 3, 4]),
    (cond("name", "is_empty"), [2, 4]),                        # null and whitespace-only
    (cond("name", "is_not_empty"), [0, 1, 3]),
    (cond("d", "ge", "2024-06-01"), [1, 3]),
    (cond("d", "between", "2023-06-01", value2="2024-12-31"), [0, 1]),
    (cond("ok", "eq", True), [0, 2, 4]),
    ({"kind": "group", "logic": "or", "items": [cond("n", "lt", 2), cond("n", "gt", 8)]}, [0, 2]),
    ({"kind": "group", "logic": "and", "items": [cond("n", "gt", 1), {"kind": "group", "logic": "or", "items": [
        cond("name", "eq", "سارا"), cond("n", "ge", 10)]}]}, [1, 2]),
], ids=lambda x: str(x)[:40])
def test_filter_conditions(where: dict, expected: list[int]) -> None:  # type: ignore[type-arg]
    assert filter_plan(DF, where)["i"].to_list() == expected


@pytest.mark.parametrize(("where", "code", "path"), [
    (cond("n", "contains", "x"), "type_mismatch", "/params/where/op"),
    (cond("name", "gt", "a", ), "type_mismatch", None),  # gt on text is allowed (ordering): see below
    (cond("n", "eq", "text"), "type_mismatch", "/params/where/value"),
    (cond("n", "gt", None), "invalid_param", "/params/where/value"),
    (cond("d", "eq", "not-a-date"), "type_mismatch", "/params/where/value"),
    (cond("ok", "gt", True), "type_mismatch", "/params/where/op"),
    ({"kind": "group", "items": [cond("n", "gt", 1), cond("n", "eq", "x")]}, "type_mismatch",
     "/params/where/items/1/value"),
])
def test_filter_type_errors_point_at_the_node(where: dict, code: str, path: str | None) -> None:  # type: ignore[type-arg]
    if path is None:
        assert filter_plan(DF, where).height >= 0
        return
    with pytest.raises(DataOpsError) as e:
        filter_plan(DF, where)
    assert (e.value.errors[0].code, e.value.errors[0].path) == (code, path)


def test_filter_is_deterministic() -> None:
    w = {"kind": "group", "logic": "or", "items": [cond("n", "gt", 1), cond("name", "is_empty")]}
    assert filter_plan(DF, w).equals(filter_plan(DF, w))


# ------------------------------------------------------------ through the executor on a sheet
def sheet() -> FakeExecContext:
    ctx = FakeExecContext()
    ctx.fill([[txt("نام"), txt("نمره")], [txt("گل"), num(3)], [txt("آب"), num(1)], [txt("باران"), num(2)],
              [txt("آب"), num(1)]])
    return ctx


def run(type_: str, ctx: FakeExecContext, **params):  # type: ignore[no-untyped-def]
    return Operation(type=type_, target=SheetRangeTarget(range=ctx.rng(0, 0, 4, 1)), params=params)


def test_sort_on_a_sheet_is_one_delta_and_undoable() -> None:
    ex, ctx = DataOpsExecutor(), sheet()
    original = ctx.snapshot()
    res = ex.apply(run("sort", ctx, keys=[{"column": "نام"}]), ctx)
    assert res.status == "ok" and ctx.writes == 1
    assert [ctx.grid[(r, 0)].v.s for r in range(1, 5)] == ["آب", "آب", "باران", "گل"]  # type: ignore[union-attr]
    ctx.apply_delta(res.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original


def test_remove_duplicates_on_a_sheet_clears_the_tail_and_undoes() -> None:
    ex, ctx = DataOpsExecutor(), sheet()
    original = ctx.snapshot()
    res = ex.apply(run("remove_duplicates", ctx), ctx)
    assert res.status == "ok" and res.affected.rows == 3  # type: ignore[union-attr]
    assert (4, 0) not in ctx.grid and ctx.grid[(3, 0)].v == txt("باران")
    ctx.apply_delta(res.delta, inverse=True)  # type: ignore[arg-type]
    assert ctx.snapshot() == original


def test_sort_refuses_formulas_by_default() -> None:
    ex, ctx = DataOpsExecutor(), sheet()
    ctx.put(1, 1, num(3), f="=1+2")
    res = ex.apply(run("sort", ctx, keys=[{"column": "نام"}]), ctx)
    assert res.status == "error" and res.errors[0].code == "range_has_formulas"


def test_nested_unknown_column_path() -> None:
    ex, ctx = DataOpsExecutor(), sheet()
    where = {"kind": "group", "items": [cond("نمره", "gt", 1), cond("بدون_ستون", "eq", 1)]}
    errs = ex.validate(run("filter", ctx, where=where), ctx)
    assert [(e.code, e.path) for e in errs] == [("unknown_column", "/params/where/items/1/column")]


def test_filter_preview_never_writes() -> None:
    ex, ctx = DataOpsExecutor(), sheet()
    before = ctx.snapshot()
    pv = ex.preview(run("filter", ctx, where=cond("نمره", "gt", 1)), ctx, 10)
    assert pv.rows == [["گل", 3.0], ["باران", 2.0]] and pv.total_rows == 2
    assert ctx.snapshot() == before and ctx.writes == 0


def test_filter_apply_on_a_sheet_without_a_table_store_is_a_typed_error_and_writes_nothing() -> None:
    ex, ctx = DataOpsExecutor(), sheet()
    before = ctx.snapshot()
    res = ex.apply(run("filter", ctx, where=cond("نمره", "gt", 1)), ctx)
    assert res.status == "error" and res.errors[0].code == "not_implemented"
    assert ctx.snapshot() == before and ctx.writes == 0


# ------------------------------------------------------------ persian helpers
def test_variant_fold() -> None:
    out = pl.DataFrame({"w": ["كي", "کی", "۱۲۳", "١٢٣", "ک‌ـتاب"]}).select(variant_fold(pl.col("w")))["w"].to_list()
    assert out == ["کی", "کی", "123", "123", "کتاب"]
