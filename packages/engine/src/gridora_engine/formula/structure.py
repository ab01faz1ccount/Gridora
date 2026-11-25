"""Reference rewriting for inserted / deleted rows and columns (Excel's rules).

`shift_formula` returns the new formula text and whether the rewrite is LOSSY, i.e. cannot be undone by
the opposite operation alone (a deleted cell or range end was referenced). The caller records the old text
of lossy formulas so undo can restore them exactly.
"""
from __future__ import annotations

import re

from .parser import _unquote_sheet, tokenize
from .refs import CELL_RE, MAX_COLS, MAX_ROWS, col_to_index, index_to_col

_COL_ONLY = re.compile(r"^(\$?)([A-Za-z]{1,3})$")
_ROW_ONLY = re.compile(r"^(\$?)(\d+)$")


def transform_index(i: int, op: str, at: int, count: int) -> int | None:
    """New position of one row/column index, or None when it was deleted."""
    if op == "insert":
        return i + count if i >= at else i
    if i < at:
        return i
    if i >= at + count:
        return i - count
    return None


def range_axis(lo: int, hi: int, op: str, at: int, count: int, limit: int) -> tuple[tuple[int, int] | None, bool]:
    """Rewrite the inclusive range [lo, hi] on one axis. Returns (new range or None, lossy)."""
    if op == "insert":
        new_lo = lo + count if lo >= at else lo
        new_hi = hi + count if hi >= at else hi
        if new_lo >= limit:
            return None, True
        if new_hi >= limit:
            return (new_lo, limit - 1), True
        return (new_lo, new_hi), False
    end = at + count  # first index after the deleted block
    if hi < at:
        return (lo, hi), False
    if lo >= end:
        return (lo - count, hi - count), False
    if lo < at and hi >= end:  # the block lies strictly inside the range: it just gets shorter
        return (lo, hi - count), False
    if lo >= at and hi >= end:  # the start was deleted
        return (at, hi - count), True
    if lo < at:  # the end was deleted
        return (lo, at - 1), True
    return None, True  # everything was deleted


def _cell_text(r: int, c: int, ra: str, ca: str) -> str:
    return f"{ca}{index_to_col(c)}{ra}{r + 1}"


def _shift_area(area: str, axis: str, op: str, at: int, count: int) -> tuple[str, bool]:
    parts = area.split(":")
    limit = MAX_ROWS if axis == "row" else MAX_COLS
    if len(parts) == 1 or len(parts) == 2 and CELL_RE.match(parts[0]) and CELL_RE.match(parts[1]):
        ms = [CELL_RE.match(p) for p in parts]
        if any(m is None for m in ms):
            return area, False
        cells: list[tuple[int, int, str, str]] = [
            (int(m.group(4)) - 1, col_to_index(m.group(2)), m.group(3), m.group(1)) for m in ms if m
        ]
        vals: list[int] = [x[0] if axis == "row" else x[1] for x in cells]
        lo, hi = min(vals), max(vals)
        new, lossy = range_axis(lo, hi, op, at, count, limit)
        if new is None:
            return "#REF!", True
        first, last = cells[0], cells[-1]
        if len(cells) == 1:
            r, c = (new[0], first[1]) if axis == "row" else (first[0], new[0])
            return _cell_text(r, c, first[2], first[3]), lossy
        # keep the original corner order and $ flags: the low corner takes the new low value
        lo_cell, hi_cell = (first, last) if vals[0] <= vals[-1] else (last, first)
        if axis == "row":
            a = _cell_text(new[0], lo_cell[1], lo_cell[2], lo_cell[3])
            b = _cell_text(new[1], hi_cell[1], hi_cell[2], hi_cell[3])
        else:
            a = _cell_text(lo_cell[0], new[0], lo_cell[2], lo_cell[3])
            b = _cell_text(hi_cell[0], new[1], hi_cell[2], hi_cell[3])
        return f"{a}:{b}", lossy
    if len(parts) == 2:
        ca, cb = _COL_ONLY.match(parts[0]), _COL_ONLY.match(parts[1])
        if ca and cb:  # whole columns: rows are unaffected
            if axis == "row":
                return area, False
            lo, hi = sorted((col_to_index(ca.group(2)), col_to_index(cb.group(2))))
            new, lossy = range_axis(lo, hi, op, at, count, MAX_COLS)
            if new is None:
                return "#REF!", True
            return f"{ca.group(1)}{index_to_col(new[0])}:{cb.group(1)}{index_to_col(new[1])}", lossy
        ra, rb = _ROW_ONLY.match(parts[0]), _ROW_ONLY.match(parts[1])
        if ra and rb:  # whole rows: columns are unaffected
            if axis == "col":
                return area, False
            lo, hi = sorted((int(ra.group(2)) - 1, int(rb.group(2)) - 1))
            new, lossy = range_axis(lo, hi, op, at, count, MAX_ROWS)
            if new is None:
                return "#REF!", True
            return f"{ra.group(1)}{new[0] + 1}:{rb.group(1)}{new[1] + 1}", lossy
    return area, False


def refers_to(text: str, own_sheet: str, target: str) -> bool:
    """Does the formula text contain a reference into `target`?"""
    want = target.casefold()
    try:
        toks = tokenize(text)
    except ValueError:
        return False
    for t in toks:
        if t.kind == "ref":
            name = _unquote_sheet(t.value[0]) or own_sheet
            if name.casefold() == want:
                return True
    return False


def shift_formula(text: str, own_sheet: str, target: str, axis: str, op: str, at: int, count: int) -> tuple[str, bool]:
    """Rewrite every reference into sheet `target` for the given insert/delete. Other text is untouched."""
    want = target.casefold()
    try:
        toks = tokenize(text)
    except ValueError:
        return text, False
    out: list[str] = []
    last = 0
    lossy = False
    for t in toks:
        if t.kind != "ref":
            continue
        sheet_text, area = t.value
        name = _unquote_sheet(sheet_text) or own_sheet
        if name.casefold() != want:
            continue
        new_area, lz = _shift_area(area, axis, op, at, count)
        lossy = lossy or lz
        if new_area == area:
            continue
        out.append(text[last : t.pos])
        out.append(new_area if new_area == "#REF!" else (sheet_text or "") + new_area)
        last = t.end
    if not out:
        return text, lossy
    out.append(text[last:])
    return "".join(out), lossy
