"""Range snapshot blobs (ADR-014/015): a deterministic, versioned, compressed columnar format.

Profile R of DESIGN.md 0.7: the exact content of a rectangle of one sheet (values, style ids,
formula text). Layout (all integers little-endian):

    header  b"GRSB" | version u16 | flags u16 | rows u32 | cols u32 | body_len u64 | sha256(body) 32B
    body    zlib(level 6) of: per column [tags: rows B][styles: rows H][vals: rows d],
            string table [count u32 | (len u32, utf-8)...], formulas [count u32 | (row u32, col u32,
            len u32, utf-8)...]

Identical content gives identical bytes (no timestamps, strings in first-appearance order). The
decoder validates every size against ResourceLimits before allocating, decompresses with a byte
budget, verifies the SHA-256 and never evaluates anything. Not an authentication scheme: integrity only.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from array import array
from dataclasses import dataclass

from ..errors import GridoraEngineError
from ..limits import ResourceLimits
from .values import ERR, ERR_CODES, NOVAL, STR
from .workbook import SheetState, WorkbookState

MAGIC = b"GRSB"
VERSION = 1
_HEADER = struct.Struct("<4sHHIIQ32s")
_MAX_TAG = NOVAL


def _fail(reason: str, msg: str) -> GridoraEngineError:
    return GridoraEngineError("internal_error", reason, msg)


@dataclass
class Decoded:
    rows: int
    cols: int
    tags: list[bytes]  # per column
    styles: list[array[int]]
    vals: list[array[float]]  # STR cells hold an index into `strings`
    strings: list[str]
    formulas: list[tuple[int, int, str]]  # (row offset, col offset, text)


Cols = list[tuple[bytes, array[float], array[int]]]  # per column: tags, vals, styles


def encode_range(
    state: WorkbookState, sheet: SheetState, r0: int, c0: int, r1: int, c1: int
) -> bytes:
    """Snapshot of the CURRENT content of a rectangle (including formula text)."""
    cols: Cols = []
    for c in range(c0, c1 + 1):
        tags, vals, styles = sheet.store.column_arrays(c, r0, r1)
        cols.append((bytes(tags), vals, styles))
    forms = sorted(
        (k >> 14, k & 0x3FFF, t) for k, t in sheet.formulas.items()
        if r0 <= (k >> 14) <= r1 and c0 <= (k & 0x3FFF) <= c1
    )
    return encode_arrays(state, r1 - r0 + 1, cols, [(r - r0, c - c0, t) for r, c, t in forms])


def encode_arrays(
    state: WorkbookState, rows: int, cols_data: Cols, forms: list[tuple[int, int, str]]
) -> bytes:
    """Encode column arrays whose STR values are ids of `state.strings`."""
    cols = len(cols_data)
    out = bytearray()
    strings: list[str] = []
    index: dict[int, int] = {}
    for tags, vals, styles in cols_data:
        mapped = array("d", vals)
        for i, t in enumerate(tags):
            if t == STR:
                sid = int(vals[i])
                j = index.get(sid)
                if j is None:
                    j = index[sid] = len(strings)
                    strings.append(state.strings.get(sid))
                mapped[i] = float(j)
        sty = array("H", styles)
        if _big_endian():
            sty.byteswap()
            mapped.byteswap()
        out += tags + sty.tobytes() + mapped.tobytes()
    out += struct.pack("<I", len(strings))
    for st in strings:
        b = st.encode("utf-8", "surrogatepass")
        out += struct.pack("<I", len(b)) + b
    out += struct.pack("<I", len(forms))
    for r, c, ftext in forms:
        b = ftext.encode("utf-8", "surrogatepass")
        out += struct.pack("<III", r, c, len(b)) + b
    body = bytes(out)
    return (
        _HEADER.pack(MAGIC, VERSION, 0, rows, cols, len(body), hashlib.sha256(body).digest())
        + zlib.compress(body, 6)
    )


def to_arrays(state: WorkbookState, dec: Decoded) -> Cols:
    """Decoded snapshot -> column arrays whose STR values are ids of `state.strings`."""
    ids = [state.strings.intern(s) for s in dec.strings]
    cols: Cols = []
    for ci in range(dec.cols):
        vals = array("d", dec.vals[ci])
        for i, t in enumerate(dec.tags[ci]):
            if t == STR:
                vals[i] = float(ids[int(vals[i])])
        cols.append((dec.tags[ci], vals, dec.styles[ci]))
    return cols


def apply_arrays(
    sheet: SheetState, r0: int, c0: int, cols: Cols, forms: list[tuple[int, int, str]]
) -> bool:
    """Write column arrays and formula texts into the store (all columns or none). Returns True
    when the set of formulas in the rectangle changed (the exporter then drops calcChain)."""
    rows = len(cols[0][0])
    r1, c1 = r0 + rows - 1, c0 + len(cols) - 1
    before = [sheet.store.column_arrays(c0 + i, r0, r1) for i in range(len(cols))]
    old_forms = {k: v for k, v in sheet.formulas.items() if r0 <= (k >> 14) <= r1 and c0 <= (k & 0x3FFF) <= c1}
    done = 0
    try:
        for i, (tags, vals, styles) in enumerate(cols):
            sheet.store.write_column(c0 + i, r0, tags, vals, styles)
            done += 1
    except BaseException:
        for i in range(done):  # restore the columns already written
            t, v, st = before[i]
            sheet.store.write_column(c0 + i, r0, bytes(t), v, st)
        raise
    for k in old_forms:
        del sheet.formulas[k]
    new_forms = {((r0 + r) << 14) | (c0 + c): t for r, c, t in forms}
    sheet.formulas.update(new_forms)
    sheet.bulk_rects.append((r0, c0, r1, c1))
    changed = old_forms != new_forms
    sheet.bulk_formulas_changed = sheet.bulk_formulas_changed or changed
    return changed


def _big_endian() -> bool:
    import sys

    return sys.byteorder == "big"


def decode_range(blob: bytes, limits: ResourceLimits, rows: int, cols: int) -> Decoded:
    """Validate and decode; `rows`/`cols` are what the delta says the range is."""
    if len(blob) < _HEADER.size:
        raise _fail("snapshot.corrupt", "The stored change is damaged.")
    magic, version, _flags, h_rows, h_cols, body_len, digest = _HEADER.unpack_from(blob)
    if magic != MAGIC:
        raise _fail("snapshot.corrupt", "The stored change is damaged.")
    if version > VERSION:
        raise _fail("snapshot.unsupported_version", "The stored change was written by a newer version.")
    if (h_rows, h_cols) != (rows, cols) or rows * cols > limits.max_cells:
        raise _fail("snapshot.corrupt", "The stored change does not match its range.")
    expected_min = rows * cols * 11
    if body_len < expected_min or body_len > expected_min + limits.max_uncompressed_bytes:
        raise _fail("snapshot.corrupt", "The stored change is damaged.")
    d = zlib.decompressobj()
    try:
        body = d.decompress(blob[_HEADER.size :], body_len + 1)
        if d.unconsumed_tail or d.unused_data or not d.eof or len(body) != body_len:
            raise ValueError
    except (zlib.error, ValueError):
        raise _fail("snapshot.corrupt", "The stored change is damaged.") from None
    if hashlib.sha256(body).digest() != digest:
        raise _fail("snapshot.corrupt", "The stored change failed its integrity check.") from None
    pos = 0
    tags: list[bytes] = []
    styles: list[array[int]] = []
    vals: list[array[float]] = []
    swap = _big_endian()
    for _ in range(cols):
        tg_col = body[pos : pos + rows]
        pos += rows
        if tg_col.translate(None, bytes(range(_MAX_TAG + 1))):
            raise _fail("snapshot.corrupt", "The stored change is damaged.")
        sty = array("H")
        sty.frombytes(body[pos : pos + 2 * rows])
        pos += 2 * rows
        vv = array("d")
        vv.frombytes(body[pos : pos + 8 * rows])
        pos += 8 * rows
        if swap:
            sty.byteswap()
            vv.byteswap()
        tags.append(bytes(tg_col))
        styles.append(sty)
        vals.append(vv)

    def u32() -> int:
        nonlocal pos
        if pos + 4 > len(body):
            raise _fail("snapshot.corrupt", "The stored change is damaged.")
        (v,) = struct.unpack_from("<I", body, pos)
        pos += 4
        return int(v)

    def text() -> str:
        nonlocal pos
        n = u32()
        if pos + n > len(body):
            raise _fail("snapshot.corrupt", "The stored change is damaged.")
        s = body[pos : pos + n].decode("utf-8", "surrogatepass")
        pos += n
        return s

    n_str = u32()
    if n_str > rows * cols:
        raise _fail("snapshot.corrupt", "The stored change is damaged.")
    strings = [text() for _ in range(n_str)]
    n_f = u32()
    if n_f > rows * cols:
        raise _fail("snapshot.corrupt", "The stored change is damaged.")
    formulas: list[tuple[int, int, str]] = []
    for _ in range(n_f):
        r, c = u32(), u32()
        if r >= rows or c >= cols:
            raise _fail("snapshot.corrupt", "The stored change is damaged.")
        formulas.append((r, c, text()))
    if pos != len(body):
        raise _fail("snapshot.corrupt", "The stored change is damaged.")
    for ci in range(cols):  # indices must point inside their tables
        for i, tg in enumerate(tags[ci]):
            if tg == STR and not 0 <= vals[ci][i] < n_str:
                raise _fail("snapshot.corrupt", "The stored change is damaged.")
            if tg == ERR and not 0 <= vals[ci][i] < len(ERR_CODES):
                raise _fail("snapshot.corrupt", "The stored change is damaged.")
    return Decoded(rows, cols, tags, styles, vals, strings, formulas)
