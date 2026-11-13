"""STUB i18n catalog for the stub operations (flat key -> text), like gridora_dataops.catalog."""

from __future__ import annotations

_FA = {
    "ops.category.order": "مرتب‌سازی",
    "ops.category.clean": "پاک‌سازی",
    "ops.sort.label": "مرتب‌سازی",
    "ops.sort.description": "مرتب‌سازی سطرها بر اساس یک یا چند ستون",
    "ops.find_replace.label": "جستجو و جایگزینی",
    "ops.find_replace.description": "جایگزینی متن در محدوده انتخاب‌شده",
    "ops.remove_duplicates.label": "حذف تکراری‌ها",
    "ops.remove_duplicates.description": "حذف سطرهای تکراری بر اساس ستون‌های انتخابی",
}
_EN = {
    "ops.category.order": "Order",
    "ops.category.clean": "Clean",
    "ops.sort.label": "Sort",
    "ops.sort.description": "Sort rows by one or more columns",
    "ops.find_replace.label": "Find and replace",
    "ops.find_replace.description": "Replace text in the selected range",
    "ops.remove_duplicates.label": "Remove duplicates",
    "ops.remove_duplicates.description": "Remove duplicate rows by the chosen columns",
}


def catalog(locale: str) -> dict[str, str]:
    return dict(_FA if locale.lower().startswith("fa") else _EN)
