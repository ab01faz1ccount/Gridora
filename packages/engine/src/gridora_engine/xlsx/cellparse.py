"""Cell-level XML events -> SheetStore. Shared by lazy window parsing and the eager fallback."""
from __future__ import annotations

import re
from array import array
from dataclasses import dataclass, field

from ..errors import import_failed, unsupported_workbook
from ..limits import ResourceLimits
from ..model.dates import iso_to_serial
from ..model.sheet import SheetStore
from ..model.values import BOOL, ERR, ERR_CODES, NOVAL, NUM, STR, StringTable
from ..package.xmlsafe import local as _local

EXCEL_ROWS = 1_048_576
EXCEL_COLS = 16_384
ERR_INDEX = {c: i for i, c in enumerate(ERR_CODES)}
# formula kinds kept in SheetCtx.fkind (absent = ordinary formula)
SHARED_MASTER, SHARED_CHILD, ARRAY, DATA_TABLE = 2, 3, 4, 5


_REF_RE = re.compile(r"([A-Za-z]{1,3})([0-9]+)\Z")
_COL_CACHE: dict[str, int] = {}


def parse_ref(ref: str) -> tuple[int, int]:
    """'AB12' -> (row0, col0). ValueError if malformed; OverflowError outside Excel's limits."""
    m = _REF_RE.match(ref)
    if m is None:
        raise ValueError("malformed")
    letters = m.group(1)
    col = _COL_CACHE.get(letters)
    if col is None:
        col = 0
        for ch in letters.upper():
            col = col * 26 + ord(ch) - 64
        _COL_CACHE[letters] = col
    row = int(m.group(2))
    if not (1 <= row <= EXCEL_ROWS and 1 <= col <= EXCEL_COLS):
        raise OverflowError("out of range")
    return row - 1, col - 1


@dataclass
class Findings:
    """Anomalies found while parsing cells lazily; surfaced in the export report."""

    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)

    def add(self, code: str, where: str) -> None:
        self.counts[code] = self.counts.get(code, 0) + 1
        s = self.samples.setdefault(code, [])
        if len(s) < 5:
            s.append(where)


@dataclass
class SheetCtx:
    name: str
    store: SheetStore
    strings: StringTable
    sst: list[str]
    sst_cache: array[int]
    limits: ResourceLimits
    findings: Findings
    formulas: dict[int, str] = field(default_factory=dict)  # (r<<14)|c -> text without '='
    fkind: dict[int, int] = field(default_factory=dict)
    array_ranges: list[tuple[int, int, int, int]] = field(default_factory=list)

    def reset_cells(self) -> None:
        self.formulas.clear()
        self.fkind.clear()
        self.array_ranges.clear()


_LN: dict[str, str] = {}


def local(name: str) -> str:
    ln = _LN.get(name)
    if ln is None:
        ln = _local(name)
        if len(_LN) < 512:  # bounded: names come from untrusted XML
            _LN[name] = ln
    return ln


class CellParser:
    def __init__(self, ctx: SheetCtx) -> None:
        self.ctx = ctx
        self.row = -1
        self.col = -1
        self.rows_seen: list[int] = []
        self._in_c = self._in_v = self._in_f = self._in_is = self._in_t = self._in_rph = False
        self._t = ""
        self._s = 0
        self._ref_r = self._ref_c = 0
        self._vbuf: list[str] = []
        self._fbuf: list[str] = []
        self._isbuf: list[str] = []
        self._fattrs: dict[str, str] = {}
        self._has_f = False
        self._ftext = ""

    def start(self, name: str, attrs: dict[str, str]) -> None:
        ln = local(name)
        if ln == "c":
            self._in_c = True
            self._t = attrs.get("t", "n")
            try:
                s = int(attrs.get("s", "0"))
            except ValueError:
                s = 0
            self._s = s if 0 <= s <= 65535 else 0
            ref = attrs.get("r")
            try:
                if ref is not None:
                    self._ref_r, self._ref_c = parse_ref(ref)
                    if self.row >= 0 and self._ref_r != self.row:
                        raise ValueError("cell row differs from its row element")
                else:
                    self._ref_r, self._ref_c = max(self.row, 0), self.col + 1
                    if self._ref_c >= EXCEL_COLS:
                        raise OverflowError("out of range")
            except OverflowError:
                raise unsupported_workbook(
                    "sheet.dimension_exceeded", "A cell lies outside the limits of a worksheet."
                ) from None
            except ValueError:
                raise import_failed(
                    "sheet.bad_cell_reference", "A cell reference in a worksheet is invalid."
                ) from None
            self.col = self._ref_c
            self._vbuf, self._fbuf, self._isbuf = [], [], []
            self._has_f = False
            self._ftext = ""
            self._fattrs = {}
            self._has_v = False
            self._has_is = False
        elif not self._in_c:
            if ln == "row":
                try:
                    self.row = int(attrs["r"]) - 1 if "r" in attrs else self.row + 1
                except ValueError:
                    raise import_failed("sheet.bad_row", "A row number in a worksheet is invalid.") from None
                if not 0 <= self.row < EXCEL_ROWS:
                    raise unsupported_workbook(
                        "sheet.dimension_exceeded", "A row lies outside the limits of a worksheet."
                    )
                self.col = -1
                self.rows_seen.append(self.row)
        elif ln == "v":
            self._in_v = True
            self._has_v = True
        elif ln == "f":
            self._in_f, self._has_f, self._fattrs = True, True, attrs
        elif ln == "is":
            self._in_is, self._has_is = True, True
        elif ln == "rPh":
            self._in_rph = True
        elif ln == "t" and self._in_is and not self._in_rph:
            self._in_t = True

    def chars(self, text: str) -> None:
        if self._in_v:
            self._vbuf.append(text)
        elif self._in_f:
            self._fbuf.append(text)
        elif self._in_t:
            self._isbuf.append(text)

    def end(self, name: str) -> None:
        ln = local(name)
        if ln == "v":
            self._in_v = False
        elif ln == "f":
            self._in_f = False
            self._ftext = "".join(self._fbuf).strip()
        elif ln == "t":
            self._in_t = False
        elif ln == "rPh":
            self._in_rph = False
        elif ln == "is":
            self._in_is = False
        elif ln == "c" and self._in_c:
            self._in_c = False
            self._finish_cell()

    # -- cell completion ----------------------------------------------------------------------
    def _finish_cell(self) -> None:
        ctx, r, c = self.ctx, self._ref_r, self._ref_c
        key = (r << 14) | c
        if self._has_f:
            kind = self._fattrs.get("t", "normal")
            if kind == "shared":
                if self._ftext:
                    ctx.formulas[key] = self._ftext
                    ctx.fkind[key] = SHARED_MASTER
                else:
                    ctx.fkind[key] = SHARED_CHILD
            elif kind == "array":
                ctx.formulas[key] = self._ftext
                ctx.fkind[key] = ARRAY
                self._array_range(r, c)
            elif kind == "dataTable":
                ctx.fkind[key] = DATA_TABLE
            else:
                ctx.formulas[key] = self._ftext
        tag, val = self._value(r, c)
        if tag == 0:
            if self._has_f:
                ctx.store.put(r, c, NOVAL, 0.0, self._s)
            return
        ctx.store.put(r, c, tag, val, self._s)

    def _array_range(self, r: int, c: int) -> None:
        ref = self._fattrs.get("ref", "")
        try:
            a, _, b = ref.partition(":")
            r0, c0 = parse_ref(a)
            r1, c1 = parse_ref(b or a)
        except (ValueError, OverflowError):
            r0, c0, r1, c1 = r, c, r, c
        self.ctx.array_ranges.append((r0, c0, max(r0, r1), max(c0, c1)))

    def _value(self, r: int, c: int) -> tuple[int, float]:
        ctx, t = self.ctx, self._t
        where = f"{ctx.name}!R{r + 1}C{c + 1}"
        if t == "inlineStr":
            if not self._has_is:
                return 0, 0.0
            return self._text("".join(self._isbuf))
        if not self._has_v:
            return 0, 0.0
        txt = "".join(self._vbuf).strip() if t != "str" else "".join(self._vbuf)
        if t == "s":
            try:
                i = int(txt)
                if not 0 <= i < len(ctx.sst):
                    raise ValueError
            except ValueError:
                ctx.findings.add("xlsx.cell_value_invalid", where)
                return ERR, float(ERR_INDEX["#VALUE!"])
            tid = ctx.sst_cache[i]
            if tid < 0:
                tid = ctx.strings.intern(ctx.sst[i])
                ctx.sst_cache[i] = tid
            return STR, float(tid)
        if t == "str":
            return self._text(txt)
        if t == "b":
            return BOOL, 1.0 if txt in ("1", "true") else 0.0
        if t == "e":
            idx = ERR_INDEX.get(txt)
            if idx is None:
                ctx.findings.add("xlsx.error_value.unmapped", where)
                idx = ERR_INDEX["#VALUE!"]
            return ERR, float(idx)
        if t == "d":
            try:
                return NUM, iso_to_serial(txt)
            except ValueError:
                ctx.findings.add("xlsx.cell_value_invalid", where)
                return ERR, float(ERR_INDEX["#VALUE!"])
        try:  # "n" and anything unknown: a number
            v = float(txt)
            if v - v != 0.0:
                raise ValueError
            return NUM, v
        except ValueError:
            ctx.findings.add("xlsx.cell_value_invalid", where)
            return ERR, float(ERR_INDEX["#VALUE!"])

    def _text(self, s: str) -> tuple[int, float]:
        if len(s) > self.ctx.limits.max_field_chars:
            raise import_failed("xlsx.string_too_long", "A cell text is longer than 32,767 characters.")
        return STR, float(self.ctx.strings.intern(s))
