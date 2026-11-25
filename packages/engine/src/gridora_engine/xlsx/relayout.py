"""Export a sheet whose rows or columns were inserted / deleted: its whole <sheetData> is regenerated
from the cell store, and the pieces of the original XML that depend on positions (row heights and
visibility, column widths, the dimension hint) are replayed through the recorded operations.

Only sheets that passed structure._check_package get here, so nothing else in the part holds coordinates.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from ..formula.refs import MAX_COLS
from ..formula.structure import range_axis, transform_index
from ..model.sheet import _KEY_ROWS, CHUNK_SHIFT
from ..model.values import StringTable
from ..model.workbook import SheetState
from .rowpatch import _COPY, _DIMENSION, cell_xml, check_fragment
from .sheetsource import ROW_RE, SheetSource
from .textenc import col_letters

_ROW_STRIP = re.compile(rb'\s(?:r|spans|x14ac:dyDescent)="[^"]*"')
_COLS = re.compile(rb"<cols>.*?</cols>", re.DOTALL)
_COL = re.compile(rb"<col\b([^>]*?)/>")
_MIN = re.compile(rb'\bmin="(\d+)"')
_MAX = re.compile(rb'\bmax="(\d+)"')


def replayed_row_attrs(src: SheetSource, ops: list[tuple[str, str, int, int]]) -> dict[int, bytes]:
    """Attributes of the original <row> tags (height, hidden, style, outline) at their NEW row numbers."""
    mm = src.mm
    assert mm is not None
    out: dict[int, bytes] = {}
    for i, r in enumerate(src.row_nums):
        m = ROW_RE.match(mm, src.row_starts[i])
        attrs = _ROW_STRIP.sub(b"", m.group(1)).strip() if m else b""
        if attrs:
            out[r] = attrs
    for ax, op, at, n in ops:
        if ax != "row":
            continue
        moved: dict[int, bytes] = {}
        for r, a in out.items():
            nr = transform_index(r, op, at, n)
            if nr is not None:
                moved[nr] = a
        out = moved
    return out


def _patch_cols(head: bytes, ops: list[tuple[str, str, int, int]]) -> bytes:
    m = _COLS.search(head)
    if m is None or not any(ax == "col" for ax, *_ in ops):
        return head
    items: list[tuple[int, int, bytes]] = []
    for cm in _COL.finditer(m.group()):
        attrs = cm.group(1)
        a, b = _MIN.search(attrs), _MAX.search(attrs)
        if a and b:
            items.append((int(a.group(1)) - 1, int(b.group(1)) - 1, attrs))
    for ax, op, at, n in ops:
        if ax != "col":
            continue
        nxt: list[tuple[int, int, bytes]] = []
        for lo, hi, attrs in items:
            new, _lossy = range_axis(lo, hi, op, at, n, MAX_COLS)
            if new is not None:
                nxt.append((new[0], new[1], attrs))
        items = nxt
    if not items:
        return head[: m.start()] + head[m.end():]
    cols = b"".join(
        b"<col" + _MAX.sub(b'max="%d"' % (hi + 1), _MIN.sub(b'min="%d"' % (lo + 1), attrs, count=1), count=1) + b"/>"
        for lo, hi, attrs in items
    )
    return head[: m.start()] + b"<cols>" + cols + b"</cols>" + head[m.end():]


def relaid_chunks(src: SheetSource, sheet: SheetState, strings: StringTable) -> Iterator[bytes]:
    mm = src.mm
    assert mm is not None
    ops = sheet.layout_ops
    store = sheet.store
    rows, cols = store.extent()
    head = _patch_cols(bytes(mm[: src.sheetdata_start]), ops)
    dim = f"A1:{col_letters(max(cols, 1) - 1)}{max(rows, 1)}".encode()
    head = _DIMENSION.sub(lambda m: m.group(1) + dim + m.group(3), head, count=1)
    yield head + b"<sheetData>"
    attrs = replayed_row_attrs(src, ops)
    total = max(rows, (max(attrs) + 1) if attrs else 0)
    formulas = sheet.formulas
    for bi in range((total + 255) >> CHUNK_SHIFT):
        chs = [store.chunks.get(c * _KEY_ROWS + bi) for c in range(cols)]
        out: list[bytes] = []
        for i in range(256):
            r = (bi << CHUNK_SHIFT) + i
            if r >= total:
                break
            cells: list[bytes] = []
            for c, ch in enumerate(chs):
                if ch is None:
                    continue
                tag, st, f = ch.tags[i], ch.styles[i], formulas.get((r << 14) | c)
                if tag or st or f:
                    x = cell_xml(r, c, tag, ch.vals[i], st, f, strings)
                    if x:
                        cells.append(x)
            a = attrs.get(r)
            if not cells and a is None:
                continue
            start = b'<row r="%d"' % (r + 1) + (b" " + a if a else b"")
            row = start + b">" + b"".join(cells) + b"</row>" if cells else start + b"/>"
            check_fragment(row)
            out.append(row)
        if out:
            yield b"".join(out)
    yield b"</sheetData>"
    for pos in range(src.close_end, src.size, _COPY):
        yield bytes(mm[pos : min(pos + _COPY, src.size)])
