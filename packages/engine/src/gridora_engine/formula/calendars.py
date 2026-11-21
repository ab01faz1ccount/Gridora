"""Calendars for formulas: Gregorian, Jalali (Solar Hijri, 33-year arithmetic rule) and Hijri (tabular Islamic civil).

Storage is always the Excel serial; a calendar is only how (year, month, day) are read and written.
Everything goes through the proleptic-Gregorian ordinal (`date.toordinal()`).

Jalali: leap years are those with year % 33 in {1,5,9,13,17,22,26,30}, anchored on 1 Farvardin 1403 = 2024-03-20
(same rule as gridora_dataops.persian.jalali). The official calendar is astronomical; the rule can diverge far
outside roughly 1300..1500.
Hijri: the tabular (civil) calendar, epoch 1 Muharram 1 AH = 622-07-19 (Julian 622-07-16 civil). It can differ by a
day from the observed (moon-sighting) calendar and from Umm al-Qura.
"""
from __future__ import annotations

from datetime import date

CALENDARS = ("gregorian", "jalali", "hijri")

JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
HIJRI_MONTHS = ["محرم", "صفر", "ربیع‌الاول", "ربیع‌الثانی", "جمادی‌الاول", "جمادی‌الثانی",
                "رجب", "شعبان", "رمضان", "شوال", "ذی‌القعده", "ذی‌الحجه"]
# index 0 = Sunday (Excel weekday 1)
PERSIAN_DAYS = ["یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"]

_J_LEAP = (1, 5, 9, 13, 17, 22, 26, 30)
_J_ANCHOR = date(2024, 3, 20).toordinal()  # 1 Farvardin 1403


def normalize(cal: object) -> str:
    c = str(cal or "gregorian").lower()
    return c if c in CALENDARS else "gregorian"


# ------------------------------------------------------------------------------------------- Jalali
def _j_leaps_before(y: int) -> int:
    n = y - 1
    q, r = divmod(n, 33)
    return q * 8 + sum(1 for x in _J_LEAP if x <= r)


def _j_leap(y: int) -> bool:
    return y % 33 in _J_LEAP


def _j_start(y: int) -> int:
    return _J_ANCHOR + 365 * (y - 1403) + _j_leaps_before(y) - _j_leaps_before(1403)


def _j_dim(y: int, m: int) -> int:
    return 31 if m <= 6 else 30 if m <= 11 else (30 if _j_leap(y) else 29)


def _j_month_off(m: int) -> int:
    return (m - 1) * 31 if m <= 7 else 186 + (m - 7) * 30


def _j_from_ord(o: int) -> tuple[int, int, int]:
    y = int((o - _J_ANCHOR) / 365.2424) + 1403
    while _j_start(y) > o:
        y -= 1
    while _j_start(y + 1) <= o:
        y += 1
    doy = o - _j_start(y)
    if doy < 186:
        return y, doy // 31 + 1, doy % 31 + 1
    doy -= 186
    return y, doy // 30 + 7, doy % 30 + 1


# -------------------------------------------------------------------------------------------- Hijri
def _h_leap(y: int) -> bool:
    return (11 * y + 14) % 30 < 11


def _h_start(y: int) -> int:
    return (y - 1) * 354 + (3 + 11 * y) // 30 + 1948440 - 1721425


def _h_dim(y: int, m: int) -> int:
    return 30 if m % 2 == 1 or (m == 12 and _h_leap(y)) else 29


def _h_month_off(m: int) -> int:
    return (59 * (m - 1) + 1) // 2


def _h_from_ord(o: int) -> tuple[int, int, int]:
    y = int((o - _h_start(1)) / 354.36667) + 1
    while _h_start(y) > o:
        y -= 1
    while _h_start(y + 1) <= o:
        y += 1
    doy = o - _h_start(y)
    m = 1
    while m < 12 and _h_month_off(m + 1) <= doy:
        m += 1
    return y, m, doy - _h_month_off(m) + 1


# ------------------------------------------------------------------------------------------- public
def days_in_month(cal: str, y: int, m: int) -> int:
    if cal == "jalali":
        return _j_dim(y, m)
    if cal == "hijri":
        return _h_dim(y, m)
    if m == 12:
        return 31
    return (date(y, m + 1, 1) - date(y, m, 1)).days


def is_leap(cal: str, y: int) -> bool:
    if cal == "jalali":
        return _j_leap(y)
    if cal == "hijri":
        return _h_leap(y)
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def from_ordinal(cal: str, o: int) -> tuple[int, int, int]:
    if cal == "jalali":
        return _j_from_ord(o)
    if cal == "hijri":
        return _h_from_ord(o)
    d = date.fromordinal(o)
    return d.year, d.month, d.day


def to_ordinal(cal: str, y: int, m: int, d: int) -> int:
    """(y, m, d) must have 1 <= m <= 12; the day may overflow and rolls into later months."""
    if cal == "jalali":
        return _j_start(y) + _j_month_off(m) + d - 1
    if cal == "hijri":
        return _h_start(y) + _h_month_off(m) + d - 1
    return date(y, m, 1).toordinal() + d - 1


def month_names(cal: str) -> list[str] | None:
    return JALALI_MONTHS if cal == "jalali" else HIJRI_MONTHS if cal == "hijri" else None


def add_months(cal: str, y: int, m: int, d: int, months: int) -> tuple[int, int, int]:
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    return ny, nm, min(d, days_in_month(cal, ny, nm))


def default_two_digit_year(cal: str, y: int) -> int:
    if 0 <= y < 100:
        return y + (1300 if cal == "jalali" else 1400 if cal == "hijri" else 1900)
    return y


def guess_calendar_of_year(y: int) -> str:
    """A year typed in text: 1200..1600 reads as Jalali, 1..1199 is not guessed, otherwise Gregorian."""
    return "jalali" if 1200 <= y <= 1600 else "gregorian"
