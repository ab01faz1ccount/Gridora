"""CSV import into a SheetStore (PLAN.md §7)."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from ..errors import import_failed, unsupported_workbook
from ..limits import Deadline, ResourceLimits
from ..model.sheet import SheetStore
from ..model.values import NUM, STR, StringTable

# Persian (U+06F0-06F9) and Arabic-Indic (U+0660-0669) digits -> Latin; Arabic thousands
# separator U+066C is also removed, decimal separator U+066B becomes ".".
_TRANS: dict[int, int | None] = {
    **{0x06F0 + i: ord("0") + i for i in range(10)},
    **{0x0660 + i: ord("0") + i for i in range(10)},
    0x066C: None,
    0x066B: ord("."),
}
_NONASCII_START = frozenset(
    chr(c) for c in (*range(0x06F0, 0x06FA), *range(0x0660, 0x066A), 0x066B)
)
_NUM_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z", re.ASCII)
_ASCII_START = frozenset("-.0123456789")


@dataclass
class CsvStats:
    rows: int = 0
    persian_normalized: int = 0
    kept_as_text: int = 0


def _sig_digits(norm: str) -> int:
    mant = norm.split("e")[0].split("E")[0]
    return len(mant.replace("-", "").replace(".", "").lstrip("0"))


def classify(tok: str, stats: CsvStats) -> tuple[int, float]:
    """Return (tag, number). Conservative: identifiers and long numbers stay text."""
    ch = tok[0]
    if tok.isascii():
        if ch not in _ASCII_START:
            if ch == "+" and len(tok) > 1 and tok[1] in "0123456789.":
                stats.kept_as_text += 1  # "+98912...": a leading + is meaningful, keep text
            return STR, 0.0
        norm, converted = tok, False
    else:
        if ch not in _NONASCII_START and ch != "-":
            return STR, 0.0
        norm, converted = tok.translate(_TRANS), True
    if not _NUM_RE.match(norm):
        return STR, 0.0
    body = norm.lstrip("-")
    if len(body) > 1 and body[0] == "0" and body[1].isdigit():
        stats.kept_as_text += 1  # 0912..., 007: identifiers keep their leading zeros
        return STR, 0.0
    if len(norm) > 15 and _sig_digits(norm) > 15:
        stats.kept_as_text += 1  # beyond double precision: do not silently round
        return STR, 0.0
    val = float(norm)
    if val - val != 0.0:  # inf
        return STR, 0.0
    if converted and norm != tok:
        stats.persian_normalized += 1
    return NUM, val


def load_into(
    store: SheetStore, strings: StringTable, text: str, delimiter: str,
    infer_types: bool, limits: ResourceLimits, deadline: Deadline,
) -> CsvStats:
    stats = CsvStats()
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    max_rows, max_cols, max_chars = limits.max_rows, limits.max_cols, limits.max_field_chars
    put = store.put
    try:
        for r, row in enumerate(reader):
            if r >= max_rows and any(row):
                raise unsupported_workbook("csv.too_many_rows", "The file has too many rows.")
            if len(row) > max_cols:
                raise unsupported_workbook("csv.too_many_columns", "The file has too many columns.")
            if r & 0x1FFF == 0:
                deadline.check()
            for c, tok in enumerate(row):
                if not tok:
                    continue
                if len(tok) > max_chars:
                    raise import_failed(
                        "csv.field_too_long", "A field is longer than 32,767 characters."
                    )
                if infer_types:
                    tag, val = classify(tok, stats)
                    if tag == NUM:
                        put(r, c, NUM, val)
                        continue
                put(r, c, STR, float(strings.intern(tok)))
            stats.rows = r + 1
    except csv.Error:
        raise import_failed("csv.malformed", "The file is not valid CSV.") from None
    return stats
