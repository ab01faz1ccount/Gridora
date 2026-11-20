"""Serial-date arithmetic for formulas (1900 system with Excel's 1900-02-29 quirk, and 1904)."""
from __future__ import annotations

import math
from datetime import date, timedelta

MAX_SERIAL = 2958465  # 9999-12-31


def serial_to_ymd(serial: float, date1904: bool = False) -> tuple[int, int, int]:
    day = math.floor(serial)
    if date1904:
        d = date(1904, 1, 1) + timedelta(days=day)
        return d.year, d.month, d.day
    if day == 0:
        return 1900, 1, 0
    if day == 60:
        return 1900, 2, 29
    base = date(1899, 12, 31) if day < 60 else date(1899, 12, 30)
    d = base + timedelta(days=day)
    return d.year, d.month, d.day


def ymd_to_serial(y: int, m: int, d: int, date1904: bool = False) -> float | None:
    """DATE() semantics: month/day overflow rolls over. None when the result is out of range."""
    if not date1904 and 0 <= y < 1900:
        y += 1900
    if y < 0 or y > 9999:
        return None
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    if y > 9999 or y < 0:
        return None
    first = date(max(y, 1), m, 1) if y >= 1 else None
    if first is None:
        return None
    if date1904:
        base = date(1904, 1, 1)
        s = (first - base).days + (d - 1)
    elif first >= date(1900, 3, 1):
        s = (first - date(1899, 12, 30)).days + (d - 1)
    else:
        s = (first - date(1899, 12, 31)).days + (d - 1)
        if s >= 60 and first < date(1900, 3, 1) and not (y == 1900 and m == 2 and d == 29):
            pass
    if s < (0 if not date1904 else -1462) or s > MAX_SERIAL:
        return None
    return float(s)


def weekday(serial: float, date1904: bool = False) -> int:
    """1 = Sunday .. 7 = Saturday."""
    day = math.floor(serial)
    if not date1904 and day < 60:
        day += 1  # the phantom day shifts everything before March 1900
    # serial 1 (1900-01-01) is a Sunday in Excel's world
    return (day - 1 + (0 if not date1904 else 5)) % 7 + 1


def split_time(serial: float) -> tuple[int, int, int]:
    frac = serial - math.floor(serial)
    secs = round(frac * 86400)
    secs %= 86400
    return secs // 3600, secs % 3600 // 60, secs % 60


def add_months(y: int, m: int, d: int, months: int) -> tuple[int, int, int]:
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    last = days_in_month(ny, nm)
    return ny, nm, min(d, last)


def days_in_month(y: int, m: int) -> int:
    if m == 12:
        return 31
    return (date(y, m + 1, 1) - date(y, m, 1)).days


def is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
