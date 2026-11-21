"""Date-column detection (E7, owner decision: Jalali by default, other calendars selectable).

A column counts as a date column when at least `threshold` of its non-empty body cells are dates, either
numbers shown with a date number format ("serial") or text that reads as a date ("YYYY/MM/DD", Persian or
Arabic-Indic digits allowed). The first row is skipped as a header when it is text and the rest is dates.
Text years 1200..1600 are Jalali; 1700 and up are Gregorian. Nothing is converted here: detection only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .values import NUM, STR
from .workbook import SheetState, WorkbookState

_DIGITS = {**{0x06F0 + i: 0x30 + i for i in range(10)}, **{0x0660 + i: 0x30 + i for i in range(10)}}
_TEXT = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$")

Kind = Literal["serial", "text"]
Calendar = Literal["gregorian", "jalali", "hijri"]


@dataclass(frozen=True, slots=True)
class DateColumn:
    col: int
    kind: Kind  # serial: real date values; text: strings that look like dates
    calendar: Calendar  # calendar the text is written in (serial values carry no calendar: "gregorian")
    header_row: bool
    dates: int  # number of date cells found
    total: int  # number of non-empty body cells


def _classify_text(s: str) -> Calendar | None:
    m = _TEXT.match(s.translate(_DIGITS))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    if 1200 <= y <= 1600:
        return "jalali"
    if y >= 1700:
        return "gregorian"
    return None


def detect_date_columns(state: WorkbookState, sheet: SheetState, max_rows: int = 5000, threshold: float = 0.8) -> list[DateColumn]:
    rows, cols = sheet.store.used_size()
    rows = min(rows, max_rows)
    if rows == 0:
        return []
    sheet.ensure(0, rows)
    info = state.styles
    date_ids = {i for i, d in enumerate(info.xf_is_date) if d} if info else set()
    out: list[DateColumn] = []
    for c in range(cols):
        tags, vals, styles = sheet.store.column_arrays(c, 0, rows - 1)
        header = bool(tags[0] == STR)
        start = 1 if header else 0
        serial = 0
        text: dict[str, int] = {}
        total = 0
        for i in range(start, rows):
            t = tags[i]
            if t == NUM:
                total += 1
                if styles[i] in date_ids:
                    serial += 1
            elif t == STR:
                total += 1
                k = _classify_text(state.strings.get(int(vals[i])))
                if k:
                    text[k] = text.get(k, 0) + 1
            elif t:
                total += 1
        if total == 0:
            continue
        if serial / total >= threshold:
            out.append(DateColumn(c, "serial", "gregorian", header, serial, total))
            continue
        if text:
            cal, n = max(text.items(), key=lambda kv: kv[1])
            if n / total >= threshold:
                out.append(DateColumn(c, "text", cal, header, n, total))  # type: ignore[arg-type]
                continue
    return out
