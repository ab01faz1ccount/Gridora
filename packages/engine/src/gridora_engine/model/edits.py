"""Applying cell contents with dirty tracking and atomic rollback (E5)."""
from __future__ import annotations

from .values import NOVAL
from .workbook import SheetState

Snap = tuple[int, float, int, str | None]  # tag, val, style, formula text (no '=')


def key_of(r: int, c: int) -> int:
    return (r << 14) | c


def snapshot(sheet: SheetState, r: int, c: int) -> Snap:
    tag, val, style = sheet.store.get(r, c)
    return tag, val, style, sheet.formulas.get(key_of(r, c))


def set_cell(sheet: SheetState, r: int, c: int, snap: Snap) -> None:
    """Set one cell to `snap` and keep sheet.dirty / sheet.orig consistent with the imported file."""
    key = key_of(r, c)
    tag, val, style, text = snap
    if key not in sheet.orig and key not in sheet.dirty:
        sheet.orig[key] = snapshot(sheet, r, c)
    if text is not None and tag == 0:
        tag = NOVAL
    sheet.store.put(r, c, tag, val, style)
    if text is None:
        sheet.formulas.pop(key, None)
    else:
        sheet.formulas[key] = text
    if snapshot(sheet, r, c) == sheet.orig[key]:
        sheet.dirty.discard(key)
        del sheet.orig[key]
    else:
        sheet.dirty.add(key)


def apply_all(sheet: SheetState, changes: list[tuple[int, int, Snap]]) -> None:
    """Apply all changes or none: on any error the already applied cells are restored."""
    done: list[tuple[int, int, Snap]] = []
    try:
        for r, c, snap in changes:
            prev = snapshot(sheet, r, c)
            set_cell(sheet, r, c, snap)
            done.append((r, c, prev))
    except BaseException:
        for r, c, prev in reversed(done):
            set_cell(sheet, r, c, prev)
        raise
