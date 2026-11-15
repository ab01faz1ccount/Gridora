"""A worksheet part spooled to a private temp file, with a byte-scanned row index (hints).

Why: the decompressed sheet can be hundreds of MB; holding it in RAM per sheet does not scale,
and the exporter needs the original row bytes to patch only edited rows (PLAN.md 5.3). The temp
file is created by tempfile.TemporaryFile (private, unlinked) and memory-mapped read-only.

The row index is a HINT built by a fast byte scan. Every parse of a row range still goes through
the safe expat path and is cross-checked against the index; any mismatch falls back to a full
safe parse (a crafted file may hide `<row ` in a comment or CDATA section).
"""
from __future__ import annotations

import mmap
import re
import tempfile
from array import array
from dataclasses import dataclass, field
from typing import IO

from ..errors import import_failed, unsupported_workbook
from ..limits import Deadline, ResourceLimits
from ..package import xmlsafe
from ..package.xmlsafe import local
from ..package.zipin import SafeZip

ROW_RE = re.compile(rb"<row\b([^>]*?)(/?)>")
R_ATTR = re.compile(rb'\br="(\d+)"')
SPANS_ATTR = re.compile(rb'\bspans="(\d+):(\d+)"')
CLOSE = b"</sheetData>"


@dataclass
class SheetFeatures:
    """Facts from everything outside <sheetData> (collected by a small, bounded parse)."""

    children: dict[str, int] = field(default_factory=dict)  # worksheet child -> count
    dimension: str = ""
    rtl: bool = False
    frozen_rows: int = 0
    frozen_cols: int = 0
    merge_cells: int = 0
    data_validations: int = 0
    conditional_formats: int = 0
    ext_uris: list[str] = field(default_factory=list)
    protected: bool = False
    views: int = 0


class FeatureCollector:
    def __init__(self) -> None:
        self.f = SheetFeatures()
        self._depth = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        ln = local(name)
        self._depth += 1
        f = self.f
        if self._depth == 2:
            f.children[ln] = f.children.get(ln, 0) + 1
            if ln == "dimension":
                f.dimension = attrs.get("ref", "")
            elif ln == "mergeCells":
                f.merge_cells += _int(attrs.get("count", "0"))
            elif ln == "dataValidations":
                f.data_validations += _int(attrs.get("count", "0"))
            elif ln == "conditionalFormatting":
                f.conditional_formats += 1
            elif ln == "sheetProtection":
                f.protected = attrs.get("sheet", "1") in ("1", "true")
        elif ln == "sheetView" and self._depth == 3:
            f.views += 1
            if f.views == 1:
                f.rtl = attrs.get("rightToLeft", "0") in ("1", "true")
        elif ln == "pane" and self._depth == 4 and attrs.get("state", "") in ("frozen", "frozenSplit"):
            f.frozen_cols = _int(attrs.get("xSplit", "0").split(".")[0])
            f.frozen_rows = _int(attrs.get("ySplit", "0").split(".")[0])
        elif ln == "ext" and self._depth == 3 and "uri" in attrs and len(f.ext_uris) < 50:
            f.ext_uris.append(attrs["uri"])

    def end(self, _name: str) -> None:
        self._depth -= 1


def count_bytes(mm: mmap.mmap, pat: bytes) -> int:
    n = 0
    i = mm.find(pat)
    while i >= 0:
        n += 1
        i = mm.find(pat, i + len(pat))
    return n


def _int(s: str) -> int:
    try:
        return max(int(s), 0)
    except ValueError:
        return 0


class SheetSource:
    """Spooled, memory-mapped sheet bytes plus the row index."""

    def __init__(self, part_name: str, tmp: IO[bytes], mm: mmap.mmap | None, size: int) -> None:
        self.part_name = part_name
        self._tmp = tmp
        self.mm = mm
        self.size = size
        self.row_nums: array[int] = array("I")
        self.row_starts: array[int] = array("Q")
        self.data_start = 0
        self.data_end = 0  # offset of </sheetData> (or data_start when self-closing/empty)
        self.close_end = 0  # first byte after </sheetData>
        self.max_span_col = 0
        self.formula_count = 0
        self.shared_count = 0
        self.array_count = 0
        self.metadata_count = 0
        self.features = SheetFeatures()
        self.indexed = False  # False: the byte scan could not be trusted -> eager full parse

    def row_end(self, i: int) -> int:
        return self.row_starts[i + 1] if i + 1 < len(self.row_starts) else self.data_end

    def slice(self, a: int, b: int) -> bytes:
        assert self.mm is not None
        return self.mm[a:b]

    def close(self) -> None:
        if self.mm is not None:
            self.mm.close()
            self.mm = None
        self._tmp.close()


def spool_and_scan(
    zin: SafeZip, part_name: str, limits: ResourceLimits, deadline: Deadline
) -> SheetSource:
    tmp = tempfile.TemporaryFile()  # noqa: SIM115 (owned by SheetSource.close)
    try:
        size = 0
        for chunk in zin.iter_chunks(part_name):
            tmp.write(chunk)
            size += len(chunk)
        tmp.flush()
        if size == 0:
            raise import_failed("xlsx.sheet_empty", "A worksheet part is empty.")
        mm = mmap.mmap(tmp.fileno(), 0, access=mmap.ACCESS_READ)
    except BaseException:
        tmp.close()
        raise
    src = SheetSource(part_name, tmp, mm, size)
    try:
        xmlsafe.check_encoding(bytes(mm[:600]))
        _scan(src, limits, deadline)
    except BaseException:
        src.close()
        raise
    return src


def _scan(src: SheetSource, limits: ResourceLimits, deadline: Deadline) -> None:
    mm = src.mm
    assert mm is not None
    i = mm.find(b"<sheetData")
    src.indexed = i >= 0
    if i >= 0:
        j = mm.find(b">", i)
        nxt = mm[i + 10 : i + 11]
        if j < 0 or nxt not in (b">", b" ", b"/", b"\n", b"\r", b"\t"):
            src.indexed = False
    if src.indexed:
        self_closing = mm[j - 1 : j] == b"/"
        src.data_start = j + 1
        if self_closing:
            src.data_end = src.close_end = j + 1
        else:
            k = mm.rfind(CLOSE)
            if k < src.data_start:
                src.indexed = False
            else:
                src.data_end, src.close_end = k, k + len(CLOSE)
    if src.indexed:
        last = -1
        n = 0
        for m in ROW_RE.finditer(mm, src.data_start, src.data_end):
            ra = R_ATTR.search(m.group(1))
            r = int(ra.group(1)) - 1 if ra else last + 1
            if r <= last:
                src.indexed = False  # not ascending: do not trust the index
                break
            if r >= limits.max_rows:
                raise unsupported_workbook(
                    "sheet.dimension_exceeded", "A row lies outside the limits of a worksheet."
                )
            sp = SPANS_ATTR.search(m.group(1))
            if sp:
                src.max_span_col = max(src.max_span_col, int(sp.group(2)))
            src.row_nums.append(r)
            src.row_starts.append(m.start())
            last = r
            n += 1
            if n & 0x3FFF == 0:
                deadline.check()
        if src.indexed and not n and src.data_end - src.data_start > 64:
            src.indexed = False  # data present but no rows found: odd markup (prefixes?)
    # cheap byte counts (approximate: they can over-count in crafted files)
    src.formula_count = count_bytes(mm, b"<f>") + count_bytes(mm, b"<f ")
    src.shared_count = count_bytes(mm, b't="shared"')
    src.array_count = count_bytes(mm, b't="array"')
    src.metadata_count = count_bytes(mm, b' cm="')
    collector = FeatureCollector()
    if src.indexed:
        frag = bytes(mm[: i]) + bytes(mm[src.close_end :])
        if len(frag) > limits.max_part_bytes:
            raise unsupported_workbook("zip.part_too_large", "A package entry is larger than allowed.")
        xmlsafe.parse(frag, start=collector.start, end=collector.end,
                      max_depth=limits.max_xml_depth, deadline=deadline)
        src.features = collector.f
