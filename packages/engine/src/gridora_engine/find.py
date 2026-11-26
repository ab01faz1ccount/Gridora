"""Find in a sheet (Ctrl+F): row-major scan over the cells' shown text, optionally formula text.

Text is compared in its folded form (gridora_contracts.persian): Arabic/Persian digit, yeh, kaf, heh, alef
and hamza variants are equal and ZWNJ, tatweel and diacritics are ignored, so a search typed on either
keyboard finds the same cell. The scan reads the sheet in row chunks through `Engine.get_cells`, so lazy sheets
are only materialised where the scan goes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from gridora_contracts.models import (
    BoolValue,
    Cell,
    DateValue,
    ErrValue,
    NumValue,
    StrValue,
    Window,
)
from gridora_contracts.persian import fold_text

from .formula.numfmt import general_text

if TYPE_CHECKING:
    from gridora_contracts.protocols import WorkbookHandle

    from .engine import GridoraEngine

CHUNK_ROWS = 500
MAX_LIMIT = 1000


def fold(s: str, match_case: bool) -> str:
    s = fold_text(s)
    return s if match_case else s.casefold()


def shown_text(cell: Cell) -> str:
    v = cell.v
    if isinstance(v, NumValue):
        return general_text(v.n)
    if isinstance(v, StrValue):
        return v.s
    if isinstance(v, BoolValue):
        return "TRUE" if v.b else "FALSE"
    if isinstance(v, ErrValue):
        return v.e
    return v.iso if isinstance(v, DateValue) else ""


def find_cells(
    engine: GridoraEngine, wb: WorkbookHandle, sheet_id: str, query: str, *, match_case: bool = False,
    whole_cell: bool = False, in_formulas: bool = False, after: tuple[int, int] | None = None,
    limit: int = 200,
) -> tuple[list[tuple[int, int]], bool]:
    """Matches after `after` (exclusive) in row-major order; the flag says there are more."""
    limit = max(1, min(limit, MAX_LIMIT))
    needle = fold(query, match_case)
    if needle == "":
        return [], False
    meta = engine._sheet(wb, sheet_id)[1].meta()
    rows, cols = meta.row_count, meta.col_count
    out: list[tuple[int, int]] = []
    start = after[0] if after else 0
    for r0 in range(start, rows, CHUNK_ROWS):
        win = engine.get_cells(wb, sheet_id, Window(row0=r0, col0=0, rows=min(CHUNK_ROWS, rows - r0), cols=cols))
        for cell in sorted(win.cells, key=lambda c: (c.r, c.c)):
            if after and (cell.r, cell.c) <= after:
                continue
            hay = [fold(shown_text(cell), match_case)]
            if in_formulas and cell.f:
                hay.append(fold(cell.f, match_case))
            if any((h == needle) if whole_cell else (needle in h) for h in hay if h != "" or whole_cell is False):
                if len(out) == limit:
                    return out, True
                out.append((cell.r, cell.c))
    return out, False
