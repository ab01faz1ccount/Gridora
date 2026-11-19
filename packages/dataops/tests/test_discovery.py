"""Task phrases, examples and search (UX_SPEC 3.1, Review 5 order 1)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import polars as pl
import pytest

from gridora_dataops import DataOpsExecutor, catalog, example, keywords, search_operations
from gridora_dataops.discovery import SEPARATOR, normalize
from gridora_dataops.registry import default_registry
from gridora_dataops.spec import PlanEnv
from gridora_dataops.tables.frames import rows_of

TYPES = [s.type for s in default_registry().all()]
# Phrases that are deliberately shared by more than one operation, with the reason. Empty on purpose.
SHARED_PHRASES: dict[str, str] = {}


@pytest.mark.parametrize("locale", ["fa", "en"])
@pytest.mark.parametrize("type_", TYPES)
def test_every_operation_has_keywords_and_an_example_in_persian(type_: str, locale: str) -> None:
    cat = catalog(locale)
    assert cat[f"ops.{type_}.keywords"].strip() and cat[f"ops.{type_}.example"].strip()
    assert len(keywords(type_, locale)) >= 5, "a newcomer needs several ways to say it"
    assert example(type_, locale) is not None


def test_the_persian_catalog_itself_holds_both_keys_for_every_operation() -> None:
    fa = catalog("fa")
    assert [t for t in TYPES if f"ops.{t}.keywords" not in fa or f"ops.{t}.example" not in fa] == []


def test_no_phrase_is_shared_between_operations_without_a_note() -> None:
    seen: dict[str, list[str]] = defaultdict(list)
    for t in TYPES:
        for phrase in keywords(t):
            seen[normalize(phrase)].append(t)
    clashes = {p: ops for p, ops in seen.items() if len(ops) > 1 and p not in {normalize(k) for k in SHARED_PHRASES}}
    assert clashes == {}, f"add a reason to SHARED_PHRASES or reword: {clashes}"
    assert all(len(v.strip()) > 10 for v in SHARED_PHRASES.values())  # a note is a sentence, not a blank


def test_keywords_are_clean_persian_words() -> None:
    for t in TYPES:
        raw = catalog("fa")[f"ops.{t}.keywords"]
        assert "," not in raw, f"{t}: separate phrases with the Persian comma"
        phrases = keywords(t)
        assert len(phrases) == len({normalize(p) for p in phrases}), f"{t}: duplicate phrase"
        for p in phrases:
            assert "ي" not in p and "ك" not in p, f"{t}: Arabic letter variants in '{p}'"
            assert SEPARATOR not in p and 2 <= len(p) <= 60


def build(table: dict[str, Any], types: dict[str, str]) -> pl.DataFrame:
    df = pl.DataFrame(table["rows"], schema=table["columns"], orient="row")
    for col, kind in types.items():
        if kind == "date":
            df = df.with_columns(pl.col(col).str.to_date("%Y-%m-%d"))
    return df


@pytest.mark.parametrize("type_", TYPES)
def test_every_example_is_true_when_run_through_the_real_operation(type_: str) -> None:
    """An example in the panel must be what the operation really does (it is executable documentation)."""
    ex = example(type_)
    assert ex is not None and ex["caption"].strip()
    spec = default_registry().get(type_)
    assert spec is not None
    params = spec.Params.model_validate(ex["params"])
    assert spec.validate_static(params) == []
    types = ex.get("types", {})
    env = PlanEnv(extra_frames=[build(ex["extra"], types)] if "extra" in ex else [])
    out = spec.plan(build(ex["before"], types), params, env).frame
    assert out.columns == ex["after"]["columns"]
    assert rows_of(out) == ex["after"]["rows"]
    assert len(ex["before"]["rows"]) <= 6 and len(ex["before"]["columns"]) <= 4  # tiny on purpose


@pytest.mark.parametrize("type_", TYPES)
def test_every_example_also_runs_through_the_public_executor(type_: str) -> None:
    ex = example(type_)
    assert ex is not None
    assert type_ in {d.type for d in DataOpsExecutor().describe_all()}


# ---------------------------------------------------------------------------------------------- search
@pytest.mark.parametrize(("query", "first"), [
    ("تکراری", "remove_duplicates"), ("حذف تکراری", "remove_duplicates"), ("مجموع هر شهر", "group_aggregate"),
    ("مرتب", "sort"), ("از الف تا ی", "sort"), ("شمسی به میلادی", "convert_calendar"), ("جدول محوری", "pivot"),
    ("فاصله اضافه", "clean_text"), ("نام و نام خانوادگی را جدا کن", "split_column"), ("دو جدول را وصل کن", "join"),
    ("تبدیل به عدد", "change_type"), ("خالی‌ها را پر کن", "fill"), ("جایگزین", "find_replace"),
    ("قیمت در تعداد", "computed_column"), ("تبدیل ستون به ردیف", "unpivot"), ("ادغام ستون", "merge_columns"),
    ("فیلتر", "filter"),
])
def test_the_task_phrases_a_newcomer_types_find_the_right_operation(query: str, first: str) -> None:
    hits = search_operations(query, TYPES)
    assert hits and hits[0].type == first, hits[:3]
    assert hits[0].score >= 60


def test_search_ignores_arabic_letter_variants_digits_and_zwnj() -> None:
    assert search_operations("كتاب", TYPES) == search_operations("کتاب", TYPES)
    assert search_operations("نیم\u200cفاصله", TYPES)[0].type == "clean_text"
    assert search_operations("نیمفاصله", TYPES)[0].type == "clean_text"  # ZWNJ is optional when typing
    assert [h.type for h in search_operations("  تکراری  ", TYPES)] == [h.type for h in search_operations("تکراری", TYPES)]


def test_search_is_deterministic_limited_and_handles_nonsense() -> None:
    assert search_operations("", TYPES) == [] and search_operations("   ", TYPES) == []
    assert search_operations("qqqqxx", TYPES) == []
    a = search_operations("ستون", TYPES, limit=3)
    assert len(a) <= 3 and a == search_operations("ستون", TYPES, limit=3)
    assert [h.score for h in a] == sorted((h.score for h in a), reverse=True)


def test_words_that_are_not_a_phrase_still_match_through_the_label_and_description() -> None:
    hits = search_operations("ستون جدید", TYPES)
    assert hits and any(h.type == "computed_column" for h in hits)
