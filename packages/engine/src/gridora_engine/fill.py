"""Fill (drag the handle, Ctrl+D, Ctrl+R): edits that continue a range into an adjacent one.

Formulas are translated like a copy (relative references move, `$` ones stay); two or more numbers
continue as a straight line; text ending in a number counts up ("Item 1", "Item 2"); everything else repeats.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from gridora_contracts.models import Cell, CellEdit, NumValue, StrValue, Window

from .formula.parser import translate

if TYPE_CHECKING:
    from gridora_contracts.protocols import WorkbookHandle

    from .engine import GridoraEngine

_TAIL = re.compile(r"^(.*?)(\d+)$", re.DOTALL)
MAX_FILL_CELLS = 50_000


def _plain(cell: Cell | None) -> CellEdit | None:
    """The cell's content as an edit-in-place value (None for an empty cell)."""
    if cell is None:
        return None
    if cell.v is None:
        return None
    return CellEdit(r=cell.r, c=cell.c, value=cell.v)


def _line(vals: list[float | None]) -> tuple[float, float] | None:
    """(start, step) of a straight line when every value is a number and there are at least two."""
    if len(vals) < 2 or any(v is None for v in vals):
        return None
    nums = [float(v) for v in vals if v is not None]
    step = (nums[-1] - nums[0]) / (len(nums) - 1)
    return nums[0], step


def _lane(cells: list[Cell | None], count: int, reverse: bool) -> list[float | str | int]:
    """What the `count` new cells of one row/column hold, nearest to the source first. A float or a string is a
    new value; an int is the index of the source cell to repeat (formulas are translated from it)."""
    n = len(cells)
    nums = [c.v.n if c is not None and not c.f and isinstance(c.v, NumValue) else None for c in cells]
    line = _line(nums)
    tails = [_TAIL.match(c.v.s) if c is not None and not c.f and isinstance(c.v, StrValue) else None for c in cells]
    text_series = n > 0 and all(t is not None for t in tails) and len({t.group(1) for t in tails if t}) == 1
    out: list[float | str | int] = []
    for i in range(count):
        k = -(i + 1) if reverse else n + i  # position relative to the first source cell
        if line is not None:
            out.append(line[0] + line[1] * k)
        elif text_series:
            first, last = tails[0], tails[-1]
            assert first is not None and last is not None
            step = (int(last.group(2)) - int(first.group(2))) // (n - 1) if n > 1 else 1
            num = int(first.group(2)) + step * k
            width = len(first.group(2)) if first.group(2).startswith("0") else 0
            out.append(f"{first.group(1)}{max(num, 0):0{width}d}")
        else:
            out.append(n - 1 - (i % n) if reverse else i % n)
    return out


def fill_edits(
    engine: GridoraEngine, wb: WorkbookHandle, sheet_id: str, source: tuple[int, int, int, int],
    target: tuple[int, int, int, int],
) -> list[CellEdit]:
    """`source` and `target` are (r0, c0, r1, c1); the target lies against one side of the source and covers
    the same columns (fill down/up) or the same rows (fill right/left)."""
    sr0, sc0, sr1, sc1 = source
    tr0, tc0, tr1, tc1 = target
    down = tr0 > sr1 and (tc0, tc1) == (sc0, sc1)
    up = tr1 < sr0 and (tc0, tc1) == (sc0, sc1)
    right = tc0 > sc1 and (tr0, tr1) == (sr0, sr1)
    left = tc1 < sc0 and (tr0, tr1) == (sr0, sr1)
    if not (down or up or right or left):
        raise ValueError("fill.shape")
    if (tr1 - tr0 + 1) * (tc1 - tc0 + 1) > MAX_FILL_CELLS:
        raise ValueError("fill.too_large")
    win = engine.get_cells(wb, sheet_id, Window(row0=sr0, col0=sc0, rows=sr1 - sr0 + 1, cols=sc1 - sc0 + 1))
    grid: dict[tuple[int, int], Cell] = {(c.r, c.c): c for c in win.cells}
    edits: list[CellEdit] = []
    vertical = down or up
    lanes = range(sc0, sc1 + 1) if vertical else range(sr0, sr1 + 1)
    for lane in lanes:
        if vertical:
            cells = [grid.get((r, lane)) for r in range(sr0, sr1 + 1)]
            positions = list(range(tr0, tr1 + 1))
            if up:
                positions.reverse()  # nearest to the source first
        else:
            cells = [grid.get((lane, c)) for c in range(sc0, sc1 + 1)]
            positions = list(range(tc0, tc1 + 1))
            if left:
                positions.reverse()
        plan = _lane(cells, len(positions), up or left)
        n = len(cells)
        for pos, what in zip(positions, plan, strict=True):
            r, c = (pos, lane) if vertical else (lane, pos)
            if isinstance(what, float):
                edits.append(CellEdit(r=r, c=c, value=NumValue(n=what)))
            elif isinstance(what, str):
                edits.append(CellEdit(r=r, c=c, value=StrValue(s=what)))
            else:
                src = cells[what] if n else None
                if src is None:
                    edits.append(CellEdit(r=r, c=c))  # empty source: clears
                elif src.f:
                    d_row, d_col = r - src.r, c - src.c
                    edits.append(CellEdit(r=r, c=c, formula=translate(src.f.lstrip("="), d_row, d_col)))
                else:
                    e = _plain(src)
                    edits.append(CellEdit(r=r, c=c, value=e.value) if e else CellEdit(r=r, c=c))
    return edits
