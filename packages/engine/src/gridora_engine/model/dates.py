"""Excel serial dates <-> ISO strings, and date number-format classification.

1900 system: serial 1 = 1900-01-01 and serial 60 is Excel's non-existent 1900-02-29 (the
historical leap-year bug); serial 0 has no date part. 1904 system: serial 0 = 1904-01-01.
A serial below 1 with a time part is returned as a time-only string ("HH:MM:SS").
Jalali conversion is NOT done here (display-side, I18N_SPEC).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Literal

DateSystem = Literal["1900", "1904"]
MAX_SERIAL_1900 = 2958465  # 9999-12-31

_BUILTIN_DATE_IDS = frozenset(
    list(range(14, 23)) + list(range(27, 37)) + list(range(45, 48)) + list(range(50, 59))
)


def _hms(secs: int) -> str:
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def serial_to_iso(serial: float, system: DateSystem = "1900") -> str | None:
    """ISO date, datetime (fractional serial) or time-only string; None if not representable."""
    if math.isnan(serial) or serial < 0:
        return None
    day = int(serial)
    secs = round((serial - day) * 86400)
    if secs == 86400:  # rounding carried into the next day
        day, secs = day + 1, 0
    if day == 0 and secs > 0:
        return _hms(secs)
    if system == "1900":
        if day == 0 or day > MAX_SERIAL_1900:
            return None
        if day == 60:
            d = "1900-02-29"
        else:
            base = date(1899, 12, 31) if day < 60 else date(1899, 12, 30)
            d = (base + timedelta(days=day)).isoformat()
    else:
        try:
            d = (date(1904, 1, 1) + timedelta(days=day)).isoformat()
        except OverflowError:
            return None
    return d if secs == 0 else f"{d}T{_hms(secs)}"


def iso_to_serial(iso: str, system: DateSystem = "1900") -> float:
    """Inverse of serial_to_iso for date and datetime strings. Raises ValueError if invalid."""
    if system == "1900" and iso.startswith("1900-02-29"):
        rest = iso[10:]
        frac = 0.0
        if rest:
            t = datetime.fromisoformat("2000-01-01" + rest)
            frac = (t.hour * 3600 + t.minute * 60 + t.second) / 86400
        return 60.0 + frac
    dt = datetime.fromisoformat(iso)
    if system == "1904":
        base = datetime(1904, 1, 1)
    elif dt >= datetime(1900, 3, 1):
        base = datetime(1899, 12, 30)
    elif dt >= datetime(1900, 1, 1):
        base = datetime(1899, 12, 31)
    else:
        raise ValueError("date before 1900-01-01 is not representable")
    delta = dt - base
    return delta.days + delta.seconds / 86400


_QUOTED = re.compile(r'"[^"]*"')
_BRACKET = re.compile(r"\[[^\]]*\]")
_ESCAPED = re.compile(r"\\.|_.|\*.")


def is_date_format(number_format: str | None, builtin_id: int | None = None) -> bool:
    """True when a number format shows a date or time (built-in id or custom format code)."""
    if builtin_id is not None and builtin_id in _BUILTIN_DATE_IDS:
        return True
    if not number_format:
        return False
    first = _QUOTED.sub("", number_format).split(";")[0]
    if re.search(r"\[(h+|m+|s+)\]", first, re.IGNORECASE):  # elapsed time
        return True
    first = _ESCAPED.sub("", _BRACKET.sub("", first))
    if first.strip().lower() == "general":
        return False
    return re.search(r"[ydhms]", first, re.IGNORECASE) is not None
