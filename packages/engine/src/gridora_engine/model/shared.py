"""Shared formulas (XLSX `t="shared"`): only the master cell carries the text; children are
derived by shifting the master's relative references (E7)."""
from __future__ import annotations

from ..formula.parser import translate
from .workbook import SheetState

SHARED_MASTER, SHARED_CHILD = 2, 3  # same values as xlsx.cellparse (kept here to avoid an import cycle)


def master_map(sheet: SheetState) -> dict[int, int]:
    """si -> key of the master cell. Rebuilt when the sheet's formula tables grew (lazy parsing)."""
    cache = getattr(sheet, "_shared_cache", None)
    if cache is None or cache[0] != len(sheet.fkind):
        masters = {
            sheet.shared_si[k]: k
            for k, kind in sheet.fkind.items()
            if kind == SHARED_MASTER and k in sheet.shared_si
        }
        cache = (len(sheet.fkind), masters)
        sheet._shared_cache = cache  # type: ignore[attr-defined]
    return cache[1]


def child_text(sheet: SheetState, key: int) -> str | None:
    """Formula text of a shared child (without '='), or None when it is not a shared child or
    its master has not been loaded yet."""
    if sheet.fkind.get(key) != SHARED_CHILD:
        return None
    si = sheet.shared_si.get(key)
    if si is None:
        return None
    mk = master_map(sheet).get(si)
    if mk is None:
        return None
    text = sheet.formulas.get(mk)
    if text is None:
        return None
    try:
        return translate(text, (key >> 14) - (mk >> 14), (key & 0x3FFF) - (mk & 0x3FFF))
    except ValueError:
        return None


def group_members(sheet: SheetState, si: int) -> list[int]:
    return [k for k, s in sheet.shared_si.items() if s == si]
