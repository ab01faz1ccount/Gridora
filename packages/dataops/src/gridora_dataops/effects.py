"""What an operation would do, in numbers (UX_SPEC F3/section 5: "X rows would be removed", an effect-stating Apply button).

`EffectSummary` is computed from the frame before and the planned frame after, so it is exact and costs one extra pass.
It is advice for the screen; undo still restores everything inside the history window. The contract's `PreviewResult`
has no field for it yet (see CONTRACT_CHANGE in INTEGRATION.md), so it is returned by
`DataOpsExecutor.preview_with_effect`.
"""
from __future__ import annotations

from typing import Optional

import polars as pl
from pydantic import BaseModel

from .catalog import catalog

LARGE_EFFECT_CELLS = 50_000  # "large" for the extra confirmation click; the server decides, the screen only shows it
_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"


class EffectSummary(BaseModel):
    rows_before: int
    rows_after: int
    rows_removed: int = 0
    rows_added: int = 0
    columns_added: list[str] = []
    columns_removed: list[str] = []
    columns_changed: list[str] = []      # values differ (only when rows keep their identity)
    cells_changed: Optional[int] = None  # None when rows were reordered/removed/added so cells cannot be compared
    cells_emptied: int = 0               # non-empty cells that become empty (a loss the user should see)
    rows_reordered: bool = False         # same rows, different order (sort)
    new_table: bool = False              # the source is not touched; the result is a NEW table
    formulas_converted: int = 0          # formula cells in the range that become plain values
    no_change: bool = False
    destructive: bool = False            # the operation's catalog flag
    large: bool = False
    confirm_recommended: bool = False    # the screen should ask for one extra click (never a generic "are you sure")


def _same_height_diff(before: pl.DataFrame, after: pl.DataFrame, cols: list[str]) -> tuple[list[str], int, int]:
    changed_cols, cells, emptied = [], 0, 0
    for c in cols:
        a, b = before[c], after[c]
        if a.dtype != b.dtype:  # a type change rewrites every non-empty cell; only emptiness can be compared
            n = int((a.is_not_null() | b.is_not_null()).sum())
            if n:
                changed_cols.append(c)
                cells += n
                emptied += int((a.is_not_null() & b.is_null()).sum())
            continue
        diff = ~((a == b) | (a.is_null() & b.is_null())).fill_null(False)
        n = int(diff.sum())
        if n:
            changed_cols.append(c)
            cells += n
            emptied += int((diff & a.is_not_null() & b.is_null()).sum())
    return changed_cols, cells, emptied


def compute_effect(before: pl.DataFrame, after: pl.DataFrame, *, destructive: bool, new_table: bool,
                   formulas_converted: int = 0) -> EffectSummary:
    e = EffectSummary(rows_before=before.height, rows_after=after.height, new_table=new_table,
                      formulas_converted=formulas_converted, destructive=destructive)
    if new_table:  # nothing of the source changes; only the size of the new table matters
        e.large = after.height * max(after.width, 1) >= LARGE_EFFECT_CELLS
        return e
    e.columns_added = [c for c in after.columns if c not in before.columns]
    e.columns_removed = [c for c in before.columns if c not in after.columns]
    e.rows_removed = max(before.height - after.height, 0)
    e.rows_added = max(after.height - before.height, 0)
    shared = [c for c in before.columns if c in after.columns]
    if before.height == after.height:
        e.columns_changed, e.cells_changed, e.cells_emptied = _same_height_diff(before, after, shared)
        if e.cells_changed and not e.columns_added and not e.columns_removed and shared == list(after.columns):
            try:  # same rows in another order (sort)? then "cells changed" would only be noise
                reordered = before.hash_rows().sort().equals(after.select(before.columns).hash_rows().sort())
            except Exception:  # noqa: BLE001
                reordered = False
            if reordered:
                e.rows_reordered, e.cells_changed, e.columns_changed, e.cells_emptied = True, None, [], 0
    else:
        e.cells_changed = None
    e.no_change = (not e.rows_removed and not e.rows_added and not e.columns_added and not e.columns_removed
                   and not e.columns_changed and not e.rows_reordered and not formulas_converted)
    touched = (e.cells_changed or 0) + e.rows_removed * max(before.width, 1)
    e.large = touched >= LARGE_EFFECT_CELLS
    loss = bool(e.rows_removed or e.cells_emptied or e.columns_removed)  # something is lost, not merely rewritten
    e.confirm_recommended = bool(formulas_converted) or (destructive and loss and not e.no_change) or (destructive and e.large)
    return e


# ------------------------------------------------------------------------------------------------ wording
def format_number(n: int, digits: str = "persian") -> str:
    """12345 -> "۱۲٬۳۴۵" (Persian digits and thousands separator) or "12,345"."""
    s = f"{n:,}"
    if digits != "persian":
        return s
    return "".join("٬" if ch == "," else _PERSIAN[int(ch)] for ch in s)


def _t(cat: dict[str, str], key: str, n: int, digits: str) -> str:
    return cat[key].replace("{n}", format_number(n, digits))


def effect_lines(e: EffectSummary, locale: str = "fa", digits: str = "persian") -> list[str]:
    """What will happen, one short sentence per effect, most important first (for the preview panel)."""
    cat = catalog(locale)
    out: list[str] = []
    if e.new_table:
        out.append(_t(cat, "effects.new_table", e.rows_after, digits))
        if e.formulas_converted:
            pass  # the source is only read: formulas are not converted
        return out
    if e.rows_removed:
        out.append(_t(cat, "effects.rows_removed", e.rows_removed, digits))
    if e.rows_added:
        out.append(_t(cat, "effects.rows_added", e.rows_added, digits))
    if e.columns_removed:
        out.append(_t(cat, "effects.columns_removed", len(e.columns_removed), digits))
    if e.columns_added:
        out.append(_t(cat, "effects.columns_added", len(e.columns_added), digits))
    if e.cells_changed:
        out.append(_t(cat, "effects.cells_changed", e.cells_changed, digits))
    if e.cells_emptied:
        out.append(_t(cat, "effects.cells_emptied", e.cells_emptied, digits))
    if e.rows_reordered:
        out.append(_t(cat, "effects.rows_reordered", e.rows_after, digits))
    if e.formulas_converted:
        out.append(_t(cat, "effects.formulas_converted", e.formulas_converted, digits))
    return out or [cat["effects.no_change"]]


def apply_label(e: EffectSummary, locale: str = "fa", digits: str = "persian") -> str:
    """The text of the Apply button: the single most important effect (UX_SPEC section 5, "Apply with an effect-stating label")."""
    cat = catalog(locale)
    if e.new_table:
        return _t(cat, "effects.apply.new_table", e.rows_after, digits)
    for flag, key, n in ((e.rows_removed, "rows_removed", e.rows_removed), (len(e.columns_removed), "columns_removed", len(e.columns_removed)),
                         (e.formulas_converted, "formulas_converted", e.formulas_converted),
                         (len(e.columns_added), "columns_added", len(e.columns_added)),
                         (e.cells_changed or 0, "cells_changed", e.cells_changed or 0),
                         (e.rows_added, "rows_added", e.rows_added)):
        if flag:
            return _t(cat, f"effects.apply.{key}", n, digits)
    return cat["effects.apply.rows_reordered"] if e.rows_reordered else cat["effects.apply.no_change"]


def done_label(e: EffectSummary, locale: str = "fa", digits: str = "persian") -> str:
    """The toast after applying ("۱۲ ردیف حذف شد"); the screen adds the Undo link."""
    cat = catalog(locale)
    if e.new_table:
        return _t(cat, "effects.done.new_table", e.rows_after, digits)
    for flag, key, n in ((e.rows_removed, "rows_removed", e.rows_removed), (len(e.columns_removed), "columns_removed", len(e.columns_removed)),
                         (len(e.columns_added), "columns_added", len(e.columns_added)),
                         (e.cells_changed or 0, "cells_changed", e.cells_changed or 0), (e.rows_added, "rows_added", e.rows_added)):
        if flag:
            return _t(cat, f"effects.done.{key}", n, digits)
    return cat["effects.done.rows_reordered"] if e.rows_reordered else cat["effects.done.no_change"]
