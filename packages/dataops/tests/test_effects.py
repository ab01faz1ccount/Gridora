"""Effect numbers for the preview panel and the Apply button (Review 5 order 2)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fakes import ColumnarFakeExecContext, RowFakeExecContext, num, txt
from gridora_contracts.models import Column, DataTableTarget, Operation, SheetRangeTarget
from hypothesis import given, settings
from hypothesis import strategies as st

from gridora_dataops import (
    DataOpsExecutor,
    apply_label,
    catalog,
    create_table_store,
    done_label,
    effect_lines,
    format_number,
)
from gridora_dataops.effects import LARGE_EFFECT_CELLS, compute_effect

ROWS = [[txt("علی"), txt("تهران"), num(3)], [txt("سارا"), txt("كرج"), num(1)], [txt("علی"), txt("تهران"), num(3)],
        [txt("مریم"), None, num(7)]]


def sheet(cls: type = RowFakeExecContext, tmp: Path | None = None) -> Any:
    seq = iter(f"t{i}" for i in range(1, 20))
    store = create_table_store(lambda o, t, v: (tmp or Path("/nonexistent")) / o / t / f"v{v}.parquet", new_id=seq.__next__) if tmp else None
    ctx = cls(store=store)
    ctx.fill([[txt("نام"), txt("شهر"), txt("تعداد")], *ROWS])
    return ctx


def effect(ctx: Any, type_: str, **params: Any):  # type: ignore[no-untyped-def]
    op = Operation(type=type_, target=SheetRangeTarget(range=ctx.rng(0, 0, 4, 2)), params=params)
    pv, e = DataOpsExecutor().preview_with_effect(op, ctx, 10)
    return pv, e


def test_remove_duplicates_counts_the_removed_rows_and_asks_for_one_extra_click() -> None:
    ctx = sheet()
    before = ctx.snapshot()
    pv, e = effect(ctx, "remove_duplicates")
    assert (e.rows_before, e.rows_after, e.rows_removed) == (4, 3, 1) and e.destructive and e.confirm_recommended
    assert pv.total_rows == 3 and ctx.snapshot() == before and ctx.writes == 0
    assert apply_label(e) == "حذف ۱ ردیف" and done_label(e) == "۱ ردیف حذف شد"
    assert effect_lines(e) == ["۱ ردیف حذف می‌شود"]


def test_sort_reorders_without_asking_and_is_not_destructive() -> None:
    _, e = effect(sheet(), "sort", keys=[{"column": "تعداد", "direction": "desc"}])
    assert e.rows_reordered and e.cells_changed is None and not e.confirm_recommended and not e.destructive
    assert apply_label(e) == "مرتب کردن ردیف‌ها" and done_label(e) == "ردیف‌ها مرتب شدند"


def test_a_value_rewrite_counts_cells_and_columns_but_is_not_a_reason_to_ask() -> None:
    _, e = effect(sheet(), "find_replace", find="تهران", replace="طهران", columns=["شهر"])
    assert e.cells_changed == 2 and e.columns_changed == ["شهر"] and e.destructive and not e.confirm_recommended
    assert apply_label(e, digits="latin") == "تغییر 2 خانه" and apply_label(e) == "تغییر ۲ خانه"


def test_values_that_become_empty_are_called_out() -> None:
    ctx = sheet()
    ctx.put(2, 1, txt("abc"))
    _, e = effect(ctx, "change_type", column="شهر", to="int64", on_error="null")
    assert e.cells_emptied >= 1 and e.confirm_recommended
    assert any("خالی می‌شود" in line for line in effect_lines(e))


def test_a_new_table_is_not_a_destructive_effect(tmp_path: Path) -> None:
    ctx = sheet(tmp=tmp_path)
    _pv, e = effect(ctx, "group_aggregate", by=["شهر"], aggregations=[{"fn": "count"}])
    assert e.new_table and not e.confirm_recommended and e.rows_removed == 0 and e.rows_after == 3
    assert apply_label(e) == "ساخت جدول جدید (۳ ردیف)" and done_label(e) == "جدول جدید با ۳ ردیف ساخته شد"
    assert "داده‌ی اصلی تغییر نمی‌کند" in effect_lines(e)[0]


def test_converting_formulas_is_named_and_asks_even_for_a_harmless_sort() -> None:
    ctx = sheet()
    ctx.put(1, 2, num(3), f="=1+2")
    _, e = effect(ctx, "sort", keys=[{"column": "تعداد"}], formulas="convert_to_values")
    assert e.formulas_converted == 1 and e.confirm_recommended and not e.destructive
    assert apply_label(e) == "تبدیل ۱ فرمول به مقدار"
    assert any("با «واگرد» برمی‌گردد" in line for line in effect_lines(e))


def test_nothing_to_do_is_said_plainly() -> None:
    _, e = effect(sheet(), "fill", mode="down", columns=["تعداد"])
    assert e.no_change and not e.confirm_recommended
    assert effect_lines(e) == ["چیزی تغییر نمی‌کند"] and apply_label(e) == "اجرا (چیزی تغییر نمی‌کند)"


@pytest.mark.parametrize("cls", [RowFakeExecContext, ColumnarFakeExecContext])
def test_the_same_numbers_on_both_sheet_paths(cls: type) -> None:
    a = effect(sheet(RowFakeExecContext), "remove_duplicates")[1]
    b = effect(sheet(cls), "remove_duplicates")[1]
    assert a == b


def test_the_same_numbers_on_a_table_and_a_sheet(tmp_path: Path) -> None:
    ctx = sheet(tmp=tmp_path)
    ctx.store.create_from_rows(ctx, "t", [Column(name="نام", dtype="string"), Column(name="شهر", dtype="string"), Column(name="تعداد", dtype="int64")],
                               [["علی", "تهران", 3], ["سارا", "كرج", 1], ["علی", "تهران", 3], ["مریم", None, 7]])
    _, es = effect(ctx, "remove_duplicates")
    _, et = DataOpsExecutor().preview_with_effect(Operation(type="remove_duplicates", target=DataTableTarget(table_id="t1"), params={}), ctx, 10)
    assert es.model_dump() == et.model_dump()


def test_the_numbers_match_what_apply_really_does() -> None:
    ctx = sheet()
    _, e = effect(ctx, "remove_duplicates")
    res = DataOpsExecutor().apply(Operation(type="remove_duplicates", target=SheetRangeTarget(range=ctx.rng(0, 0, 4, 2)), params={}), ctx)
    assert res.affected.rows == e.rows_after and e.rows_before - e.rows_after == e.rows_removed


def test_large_changes_ask_once_when_destructive() -> None:
    n = LARGE_EFFECT_CELLS + 10
    before = pl.DataFrame({"a": list(range(n)), "b": [1] * n})
    e = compute_effect(before, before.with_columns(pl.col("b") + 1), destructive=True, new_table=False)
    assert e.large and e.confirm_recommended and e.cells_changed == n
    e2 = compute_effect(before, before.with_columns(pl.col("b") + 1), destructive=False, new_table=False)
    assert e2.large and not e2.confirm_recommended  # not destructive: no extra click


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 3), st.integers(0, 3)), max_size=20), st.integers(0, 20))
def test_row_counts_always_add_up(rows, keep) -> None:  # type: ignore[no-untyped-def]
    before = pl.DataFrame({"a": [r[0] for r in rows], "b": [r[1] for r in rows]}, schema={"a": pl.Int64, "b": pl.Int64})
    after = before.head(keep)
    e = compute_effect(before, after, destructive=True, new_table=False)
    assert e.rows_before - e.rows_removed + e.rows_added == e.rows_after
    assert e.rows_removed == max(before.height - after.height, 0)
    assert e.confirm_recommended == (e.rows_removed > 0 or (e.large and not e.no_change))


def test_number_formatting_in_both_digit_sets() -> None:
    assert format_number(1234567) == "۱٬۲۳۴٬۵۶۷" and format_number(1234567, "latin") == "1,234,567" and format_number(0) == "۰"


def test_every_effect_text_exists_in_both_locales_with_a_placeholder() -> None:
    for locale in ("fa", "en"):
        keys = [k for k in catalog(locale) if k.startswith("effects.") and not k.endswith(("no_change", "rows_reordered"))
                or k in ("effects.rows_reordered",)]
        assert len(keys) >= 20
        for k in keys:
            assert "{n}" in catalog(locale)[k], k
    for k, v in catalog("fa").items():
        if k.startswith("effects."):
            assert "ي" not in v and "ك" not in v and any("\u0600" <= c <= "\u06ff" for c in v), k
