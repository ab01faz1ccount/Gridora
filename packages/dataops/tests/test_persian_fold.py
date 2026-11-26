"""Persian/Arabic variants across the operations that offer `ignore_variants` (one shared fold)."""
from __future__ import annotations

import polars as pl
from test_m1_ops import cond, dedupe_plan, filter_plan
from test_m3_clean import fr
from test_m4_analyze import ga, jn

from gridora_dataops.persian.chars import variant_fold

# the same word typed with different keyboards / sources
KETAB = ["کتاب", "كتاب", "کِتاب", "كـتاب"]
ALEF = ["آب", "اب", "ٱب"]
HAMZA = ["مسئله", "مسیله"]  # ئ compares as ی
HAMZA2 = ["مسأله", "مساله"]  # أ compares as ا
ZWNJ = ["می‌روم", "میروم"]


def folded(values: list[str]) -> list[str]:
    return pl.DataFrame({"a": values}).select(variant_fold(pl.col("a")))["a"].to_list()


def test_every_group_of_variants_folds_to_one_form() -> None:
    for group in (KETAB, ALEF, HAMZA, HAMZA2, ZWNJ):
        assert len(set(folded(group))) == 1, group
    assert len(set(folded(["سلام", "سلم"]))) == 2  # different words stay different


def test_filter_matches_all_variants_only_when_asked() -> None:
    df = pl.DataFrame({"a": [*KETAB, *ALEF, "x"]})
    assert filter_plan(df, cond("a", "eq", "کتاب")).height == 1
    assert filter_plan(df, cond("a", "eq", "کتاب", ignore_variants=True)).height == len(KETAB)
    assert filter_plan(df, cond("a", "contains", "اب", ignore_variants=True)).height == len(KETAB) + len(ALEF)


def test_remove_duplicates_merges_variants() -> None:
    df = pl.DataFrame({"a": [*KETAB, *HAMZA, "x"]})
    assert dedupe_plan(df).height == len(df)
    assert dedupe_plan(df, ignore_variants=True)["a"].to_list() == [KETAB[0], HAMZA[0], "x"]


def test_find_replace_matches_variants_and_keeps_the_rest_of_the_cell() -> None:
    df = pl.DataFrame({"a": ["كتاب مسأله", "کتاب مسئله 1"]})
    out = fr(df, find="مسئله", replace="X", ignore_variants=True)["a"].to_list()
    assert out == ["كتاب مسأله", "کتاب X 1"]
    assert fr(df, find="کتاب", replace="X", ignore_variants=True)["a"].to_list() == ["X مسأله", "X مسئله 1"]
    assert fr(df, find="آم", replace="X", ignore_variants=True)["a"].to_list() == df["a"].to_list()  # no آم/ام in it
    assert fr(pl.DataFrame({"a": ["آب و اب"]}), find="اب", replace="X", ignore_variants=True)["a"].to_list() == ["X و X"]
    # a needle made only of ignorable characters matches exactly that, not everything
    assert fr(pl.DataFrame({"a": ["a‌b", "ab"]}), find="‌", replace="-", ignore_variants=True)["a"].to_list() == ["a-b", "ab"]


def test_join_keys_with_variants() -> None:
    right = pl.DataFrame({"k": ["كتاب", "مسأله"], "v": [1, 2]})
    left = pl.DataFrame({"name": ["کتاب", "مساله", "z"], "id": [1, 2, 3]})
    assert jn(left=left, right=right, left_on=["name"], right_on=["k"]).height == 0
    out = jn(left=left, right=right, left_on=["name"], right_on=["k"], ignore_variants=True)
    assert sorted(out["v"].to_list()) == [1, 2]


def test_group_by_merges_variants_and_shows_the_first_spelling() -> None:
    df = pl.DataFrame({"city": ["کرج", "كرج", "تهران", "کرج"], "n": [1, 2, 3, 4]})
    plain = ga(df, by=["city"], aggregations=[{"fn": "sum", "column": "n"}])
    assert plain.height == 3
    out = ga(df, by=["city"], aggregations=[{"fn": "sum", "column": "n"}], ignore_variants=True)
    assert out.columns == ["city", "sum_n"]
    assert out["city"].to_list() == ["کرج", "تهران"] and out["sum_n"].to_list() == [7, 3]
    two = ga(df.with_columns(k=pl.lit("a")), by=["k", "city"], aggregations=[{"fn": "count"}], ignore_variants=True)
    assert two.columns == ["k", "city", "count"] and two["count"].to_list() == [3, 1]
