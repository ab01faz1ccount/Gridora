"""Patch edited rows into the ORIGINAL worksheet bytes (PLAN.md 5.3).

Everything outside the rows that contain edited cells is copied byte for byte (prefix, suffix,
untouched rows, unedited cells inside a rebuilt row). Edited cells are regenerated; edited text is
written as inline strings (no sharedStrings change). Each rebuilt row is checked for
well-formedness before it is emitted.
"""
from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from xml.parsers import expat

from ..errors import import_failed
from ..formula.parser import to_file_formula
from ..model.edits import key_of
from ..model.values import BOOL, ERR, ERR_CODES, NUM, STR, StringTable
from ..model.workbook import SheetState
from ..package import xmlsafe
from .cellparse import parse_ref
from .sheetsource import ROW_RE, SheetSource
from .textenc import col_letters, encode_text, xml_escape

_SPANS = re.compile(rb'\sspans="[^"]*"')
_DIMENSION = re.compile(rb'(<dimension\b[^>]*?\bref=")([^"]*)(")')
_COPY = 1 << 20


def _num(v: float) -> str:
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def cell_xml(
    r: int, c: int, tag: int, val: float, style: int, formula: str | None, strings: StringTable,
    array_ref: str | None = None,
) -> bytes | None:
    """XML of one cell, or None when the cell is empty, unstyled and has no formula."""
    attrs = f' r="{col_letters(c)}{r + 1}"' + (f' s="{style}"' if style else "")
    fa = f' t="array" ref="{array_ref}"' if array_ref else ""
    f = f"<f{fa}>{xml_escape(to_file_formula(formula))}</f>" if formula else ""
    if tag == NUM:
        body = f'<c{attrs}>{f}<v>{_num(val)}</v></c>'
    elif tag == STR:
        text = strings.get(int(val))
        if formula:
            body = f'<c{attrs} t="str">{f}<v>{encode_text(text)}</v></c>'
        else:
            body = f'<c{attrs} t="inlineStr"><is><t xml:space="preserve">{encode_text(text)}</t></is></c>'
    elif tag == BOOL:
        body = f'<c{attrs} t="b">{f}<v>{1 if val else 0}</v></c>'
    elif tag == ERR:
        body = f'<c{attrs} t="e">{f}<v>{ERR_CODES[int(val)]}</v></c>'
    elif f:  # NOVAL / formula without a cached value
        body = f"<c{attrs}>{f}</c>"
    elif style:
        body = f"<c{attrs}/>"
    else:
        return None
    return body.encode("utf-8")


def _forbid(*_a: object) -> None:
    raise ValueError("forbidden construct")


def _cell_ranges(row: bytes) -> tuple[list[tuple[int, int]], int]:
    """For one `<row>` element: ([(column, byte offset of '<c')], offset of '</row>')."""
    starts: list[tuple[int, int]] = []
    close = len(row)
    depth = 0
    last_col = -1
    p = expat.ParserCreate()

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth, last_col
        depth += 1
        if name == "c" and depth == 2:
            ref = attrs.get("r")
            last_col = parse_ref(ref)[1] if ref else last_col + 1
            starts.append((last_col, p.CurrentByteIndex))

    def end(name: str) -> None:
        nonlocal depth, close
        if name == "row" and depth == 1:
            close = p.CurrentByteIndex
        depth -= 1

    p.StartDoctypeDeclHandler = _forbid
    p.EntityDeclHandler = _forbid
    p.StartElementHandler, p.EndElementHandler = start, end
    try:
        p.Parse(row, True)
    except (expat.ExpatError, ValueError, OverflowError):
        raise import_failed("export.row_unreadable", "A worksheet row could not be re-read for export.") from None
    return starts, close


def rebuild_row(orig: bytes, dirty_cols: dict[int, bytes | None]) -> bytes:
    """Rebuild an existing row: unedited cells keep their original bytes; `dirty_cols` maps a column
    to its regenerated XML (None = remove). The `spans` hint is dropped (it may no longer hold)."""
    m = ROW_RE.match(orig)
    if m is None:
        raise import_failed("export.row_unreadable", "A worksheet row could not be re-read for export.")
    existing: dict[int, bytes] = {}
    if m.group(2) == b"/":  # <row .../> without children
        head, tail = _SPANS.sub(b"", orig[: m.end() - 2]) + b">", b"</row>"
    else:
        cells, close = _cell_ranges(orig)
        first = cells[0][1] if cells else close
        head, tail = _SPANS.sub(b"", orig[:first]), orig[close:]
        bounds = [s for _c, s in cells[1:]] + [close]
        existing = {col: orig[s:e] for (col, s), e in zip(cells, bounds, strict=True)}
    for col, xml in dirty_cols.items():
        if xml is None:
            existing.pop(col, None)
        else:
            existing[col] = xml
    return _with_spans(head, sorted(existing)) + b"".join(existing[c] for c in sorted(existing)) + tail


def _with_spans(head: bytes, cols: list[int]) -> bytes:
    """Set the `spans` hint of a row start tag from the columns the row now holds."""
    if not cols:
        return head
    i = head.rfind(b">")
    return head[:i] + f' spans="{cols[0] + 1}:{cols[-1] + 1}"'.encode() + head[i:]


def new_row(r: int, dirty_cols: dict[int, bytes | None]) -> bytes:
    cols = sorted(c for c, x in dirty_cols.items() if x is not None)
    cells = b"".join(x for _c, x in sorted(dirty_cols.items()) if x is not None)
    return _with_spans(f'<row r="{r + 1}">'.encode(), cols) + cells + b"</row>"


def check_fragment(xml: bytes) -> None:
    """A rebuilt row must be well-formed on its own (defense in depth against writer bugs)."""
    xmlsafe.parse(xml, max_depth=8, namespaces=False)


def _array_ref(sheet: SheetState, key: int) -> str | None:
    """`A1:B2` for the anchor of an array formula (so the rewritten cell stays an array formula)."""
    if sheet.fkind.get(key) != 4:
        return None
    r, c = key >> 14, key & 0x3FFF
    for r0, c0, r1, c1 in sheet.array_ranges:
        if (r0, c0) == (r, c):
            a = f"{col_letters(c0)}{r0 + 1}"
            return a if (r0, c0) == (r1, c1) else f"{a}:{col_letters(c1)}{r1 + 1}"
    return None


def sheet_chunks(
    src: SheetSource, sheet: SheetState, strings: StringTable, new_dimension: str | None
) -> Iterator[bytes]:
    """The patched worksheet XML: original bytes with the rows that contain edits rebuilt."""
    mm = src.mm
    assert mm is not None
    by_row: dict[int, dict[int, bytes | None]] = {}
    for key in sorted(sheet.dirty):
        r, c = key >> 14, key & 0x3FFF
        tag, val, style = sheet.store.get(r, c)
        by_row.setdefault(r, {})[c] = cell_xml(r, c, tag, val, style, sheet.formulas.get(key), strings,
                                               _array_ref(sheet, key))
    rects = sheet.bulk_rects  # rectangles written in bulk: every cell inside is regenerated
    rect_rows: set[int] = set()
    for r0, _c0, r1, _c1 in rects:
        rect_rows.update(range(r0, r1 + 1))

    def cells_of_row(r: int) -> dict[int, bytes | None]:
        cols = dict(by_row.get(r, {}))
        for r0, c0, r1, c1 in rects:
            if r0 <= r <= r1:
                for c in range(c0, c1 + 1):
                    if c not in cols:
                        tag, val, style = sheet.store.get(r, c)
                        k = key_of(r, c)
                        cols[c] = cell_xml(r, c, tag, val, style, sheet.formulas.get(k), strings, _array_ref(sheet, k))
        return cols

    self_closing = src.close_end == src.data_end
    prefix = bytes(mm[: src.sheetdata_start]) + b"<sheetData>" if self_closing else bytes(mm[: src.data_start])
    if new_dimension is not None:
        prefix = _DIMENSION.sub(lambda m: m.group(1) + new_dimension.encode() + m.group(3), prefix, count=1)
    yield prefix
    nums = src.row_nums
    cursor = src.data_start
    for r in sorted(set(by_row) | rect_rows):
        row_cells = cells_of_row(r)
        idx = bisect.bisect_left(nums, r)
        pos = src.row_starts[idx] if idx < len(nums) else src.data_end
        pos = max(pos, cursor)
        for a in range(cursor, pos, _COPY):
            yield bytes(mm[a : min(a + _COPY, pos)])
        cursor = pos
        if idx < len(nums) and nums[idx] == r:
            end = src.row_end(idx)
            row_xml = rebuild_row(bytes(mm[src.row_starts[idx] : end]), row_cells)
            cursor = end
        else:
            row_xml = new_row(r, row_cells)
        check_fragment(row_xml)
        yield row_xml
    for a in range(cursor, src.data_end, _COPY):
        yield bytes(mm[a : min(a + _COPY, src.data_end)])
    yield b"</sheetData>"  # the original closing tag (or the one the self-closing form lacked)
    for a in range(src.close_end, src.size, _COPY):
        yield bytes(mm[a : min(a + _COPY, src.size)])
