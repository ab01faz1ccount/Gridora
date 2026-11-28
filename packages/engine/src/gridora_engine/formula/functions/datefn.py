from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from .. import calendars as CAL
from .. import xlerrors as E
from ..calendars import normalize
from ..dates import (
    cal_to_serial,
    days_in_month,
    is_leap,
    serial_to_cal,
    serial_to_ymd,
    split_time,
    weekday,
    ymd_to_serial,
)
from ..values import XlRaise, check, to_num
from .helpers import integer, opt_num, scalar, text
from .registry import fn


def _d1904(ctx: Any) -> bool:
    return bool(ctx.env.date1904)


def _cal(ctx: Any) -> str:
    return normalize(getattr(ctx.env, "calendar", "gregorian"))


def _serial_arg(ctx: Any, a: Any) -> float:
    v = scalar(ctx, a)
    if isinstance(v, str):
        s = parse_date_text(v, _d1904(ctx), _cal(ctx))
        if s is None:
            raise XlRaise(E.VALUE)
        return s
    x = to_num(v)
    if x < 0:
        raise XlRaise(E.NUM)
    return x


_DIGITS = {**{0x06F0 + i: 0x30 + i for i in range(10)}, **{0x0660 + i: 0x30 + i for i in range(10)}}  # Persian/Arabic-Indic
_ISO = re.compile(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$")
_MDY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\s*$", re.IGNORECASE)


_MONTHS = {n: i + 1 for i, names in enumerate([
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")]) for n in names}
_MON = r"([A-Za-z]{3,9})\.?"
_D_MON_Y = re.compile(rf"^\s*(\d{{1,2}})[-\s]{_MON}[-,\s]\s*(\d{{2}}|\d{{4}})\s*$")  # 5-Mar-2024, 5 March 2024
_MON_D_Y = re.compile(rf"^\s*{_MON}\s+(\d{{1,2}}),?\s+(\d{{2}}|\d{{4}})\s*$")  # Mar 5, 2024
_MON_Y = re.compile(rf"^\s*{_MON}\s+(\d{{4}})\s*$")  # March 2024 -> the 1st


def _year(text: str) -> int:
    y = int(text)
    return y if len(text) == 4 else (2000 + y if y < 30 else 1900 + y)  # Excel: 00-29 -> 20xx, 30-99 -> 19xx


def _named_month_date(s: str, date1904: bool) -> float | None:
    """English month names (Excel reads them in every locale of its English UI): 5-Mar-2024, 5 March 2024,
    Mar 5, 2024, March 2024. A name that is not a month, or a day that does not exist, is not a date."""
    for rx, order in ((_D_MON_Y, "dmy"), (_MON_D_Y, "mdy"), (_MON_Y, "my")):
        m = rx.match(s)
        if not m:
            continue
        g = m.groups()
        name, day, year = ((g[1], g[0], g[2]) if order == "dmy" else (g[0], g[1], g[2]) if order == "mdy"
                           else (g[0], "1", g[1]))
        mo = _MONTHS.get(name.lower())
        if mo is None:
            return None
        y, d = _year(year), int(day)
        if not 1 <= d <= days_in_month(y, mo):
            return None
        return ymd_to_serial(y, mo, d, date1904)
    return None


def parse_date_text(s: str, date1904: bool = False, cal: str = "gregorian") -> float | None:
    s = s.translate(_DIGITS)
    m = _ISO.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # in Jalali/Hijri mode a year that is clearly Gregorian (>= 1700) is still read as Gregorian
        c = "gregorian" if cal != "gregorian" and y >= 1700 else cal
        if not (1 <= mo <= 12 and 1 <= d <= CAL.days_in_month(c, y, mo)):
            return None
        ser = cal_to_serial(y, mo, d, c, date1904)
        if ser is None:
            return None
        if m.group(4):
            ser += (int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6) or 0)) / 86400
        return ser
    m = _MDY.match(s)
    if m and cal == "gregorian":
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= days_in_month(y, mo)):
            return None
        return ymd_to_serial(y, mo, d, date1904)
    named = _named_month_date(s, date1904)  # English month names are Gregorian in every calendar mode
    if named is not None:
        return named
    t = parse_time_text(s)
    return t


def parse_time_text(s: str) -> float | None:
    m = _TIME.match(s)
    if not m:
        return None
    h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    ap = (m.group(4) or "").upper()
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap == "PM" else 0)
    if h > 23 or mi > 59 or se > 59:
        return None
    return (h * 3600 + mi * 60 + se) / 86400


@fn("DATE", 3, 3)
def f_date(ctx: Any, y: Any, m: Any, d: Any) -> float:
    yy, mm, dd = integer(ctx, y), integer(ctx, m), integer(ctx, d)
    # day overflow: go through the first of the month so months roll first
    base = cal_to_serial(yy, mm, 1, _cal(ctx), _d1904(ctx))
    if base is None:
        raise XlRaise(E.NUM)
    s = base + (dd - 1)
    if s < 0 or s > 2958465:
        raise XlRaise(E.NUM)
    return s


@fn("TODAY", 0, 0, volatile=True)
def f_today(ctx: Any) -> float:
    return float(math.floor(ctx.env.now_serial()))


@fn("NOW", 0, 0, volatile=True)
def f_now(ctx: Any) -> float:
    now: float = ctx.env.now_serial()
    return now


@fn("YEAR", 1, 1)
def f_year(ctx: Any, a: Any) -> float:
    return float(serial_to_cal(_serial_arg(ctx, a), _cal(ctx), _d1904(ctx))[0])


@fn("MONTH", 1, 1)
def f_month(ctx: Any, a: Any) -> float:
    return float(serial_to_cal(_serial_arg(ctx, a), _cal(ctx), _d1904(ctx))[1])


@fn("DAY", 1, 1)
def f_day(ctx: Any, a: Any) -> float:
    return float(serial_to_cal(_serial_arg(ctx, a), _cal(ctx), _d1904(ctx))[2])


@fn("HOUR", 1, 1)
def f_hour(ctx: Any, a: Any) -> float:
    return float(split_time(_serial_arg(ctx, a))[0])


@fn("MINUTE", 1, 1)
def f_minute(ctx: Any, a: Any) -> float:
    return float(split_time(_serial_arg(ctx, a))[1])


@fn("SECOND", 1, 1)
def f_second(ctx: Any, a: Any) -> float:
    return float(split_time(_serial_arg(ctx, a))[2])


@fn("TIME", 3, 3)
def f_time(ctx: Any, h: Any, m: Any, s: Any) -> float:
    hh, mm, ss = integer(ctx, h), integer(ctx, m), integer(ctx, s)
    if hh < 0 or mm < 0 or ss < 0 or hh > 32767 or mm > 32767 or ss > 32767:
        raise XlRaise(E.NUM)
    return ((hh * 3600 + mm * 60 + ss) % 86400) / 86400


@fn("DATEVALUE", 1, 1)
def f_datevalue(ctx: Any, a: Any) -> float:
    s = parse_date_text(text(ctx, a), _d1904(ctx), _cal(ctx))
    if s is None:
        raise XlRaise(E.VALUE)
    return float(math.floor(s))


@fn("TIMEVALUE", 1, 1)
def f_timevalue(ctx: Any, a: Any) -> float:
    t = parse_time_text(text(ctx, a))
    if t is None:
        s = parse_date_text(text(ctx, a), _d1904(ctx))
        if s is None:
            raise XlRaise(E.VALUE)
        return s - math.floor(s)
    return t


@fn("WEEKDAY", 1, 2)
def f_weekday(ctx: Any, a: Any, t: Any = None) -> float:
    w = weekday(_serial_arg(ctx, a), _d1904(ctx))  # 1 = Sunday
    kind = int(opt_num(ctx, t, 1))
    if kind == 1:
        return float(w)
    if kind == 2:
        return float((w - 2) % 7 + 1)
    if kind == 3:
        return float((w - 2) % 7)
    if 11 <= kind <= 17:
        start = kind - 10  # 11 = Monday .. 17 = Sunday
        return float((w - (start % 7 + 1)) % 7 + 1)
    raise XlRaise(E.NUM)


@fn("EDATE", 2, 2)
def f_edate(ctx: Any, a: Any, m: Any) -> float:
    s = _serial_arg(ctx, a)
    cal = _cal(ctx)
    y, mo, d = serial_to_cal(s, cal, _d1904(ctx))
    ny, nm, nd = CAL.add_months(cal, y, mo, d, integer(ctx, m))
    r = cal_to_serial(ny, nm, nd, cal, _d1904(ctx))
    if r is None:
        raise XlRaise(E.NUM)
    return r


@fn("EOMONTH", 2, 2)
def f_eomonth(ctx: Any, a: Any, m: Any) -> float:
    s = _serial_arg(ctx, a)
    cal = _cal(ctx)
    y, mo, _d = serial_to_cal(s, cal, _d1904(ctx))
    ny, nm, _ = CAL.add_months(cal, y, mo, 1, integer(ctx, m))
    r = cal_to_serial(ny, nm, CAL.days_in_month(cal, ny, nm), cal, _d1904(ctx))
    if r is None:
        raise XlRaise(E.NUM)
    return r


@fn("DAYS", 2, 2)
def f_days(ctx: Any, end: Any, start: Any) -> float:
    return float(math.floor(_serial_arg(ctx, end)) - math.floor(_serial_arg(ctx, start)))


@fn("DAYS360", 2, 3)
def f_days360(ctx: Any, a: Any, b: Any, method: Any = None) -> float:
    y1, m1, d1 = serial_to_ymd(_serial_arg(ctx, a), _d1904(ctx))
    y2, m2, d2 = serial_to_ymd(_serial_arg(ctx, b), _d1904(ctx))
    european = bool(opt_num(ctx, method, 0))
    if european:
        d1, d2 = min(d1, 30), min(d2, 30)
    else:
        last1 = d1 == days_in_month(y1, m1)
        if last1:
            d1 = 30
        if d2 == 31 and d1 >= 30:
            d2 = 30
    return float((y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1))


@fn("DATEDIF", 3, 3)
def f_datedif(ctx: Any, a: Any, b: Any, unit: Any) -> float:
    s, e = math.floor(_serial_arg(ctx, a)), math.floor(_serial_arg(ctx, b))
    if s > e:
        raise XlRaise(E.NUM)
    u = text(ctx, unit).upper()
    cal = _cal(ctx)
    y1, m1, d1 = serial_to_cal(s, cal, _d1904(ctx))
    y2, m2, d2 = serial_to_cal(e, cal, _d1904(ctx))
    months = (y2 - y1) * 12 + (m2 - m1) - (1 if d2 < d1 else 0)
    if u == "D":
        return float(e - s)
    if u == "M":
        return float(months)
    if u == "Y":
        return float(months // 12)
    if u == "MD":
        if d2 >= d1:
            return float(d2 - d1)
        pm = m2 - 1 or 12
        py = y2 if m2 > 1 else y2 - 1
        return float(CAL.days_in_month(cal, py, pm) - d1 + d2)
    if u == "YM":
        return float(months % 12)
    if u == "YD":
        ay = y2 if (m2, d2) >= (m1, d1) else y2 - 1
        anniv = CAL.to_ordinal(cal, ay, m1, min(d1, CAL.days_in_month(cal, ay, m1)))
        return float(CAL.to_ordinal(cal, y2, m2, d2 or 1) - anniv)
    raise XlRaise(E.NUM)


def _holidays(ctx: Any, h: Any) -> set[int]:
    if h is None:
        return set()
    from .helpers import iter_cells

    out = set()
    for x in iter_cells(h):
        if x is None:
            continue
        out.add(math.floor(to_num(check(x))))
    return out


def _is_workday(s: int, d1904: bool, hol: set[int], weekend: set[int]) -> bool:
    return (weekday(s, d1904) - 1) not in weekend and s not in hol


def _weekend_set(ctx: Any, w: Any) -> set[int]:
    if w is None:
        return {0, 6}
    v = scalar(ctx, w)
    if isinstance(v, str):
        if len(v) != 7 or set(v) - {"0", "1"}:
            raise XlRaise(E.VALUE)
        return {i for i, ch in enumerate(v) if ch == "1"}  # Monday first
    n = int(to_num(v))
    table = {1: {0, 6}, 2: {0, 1}, 3: {1, 2}, 4: {2, 3}, 5: {3, 4}, 6: {4, 5}, 7: {5, 6},
             11: {0}, 12: {1}, 13: {2}, 14: {3}, 15: {4}, 16: {5}, 17: {6}}
    if n not in table:
        raise XlRaise(E.NUM)
    return table[n]


def _wk(s: int, d1904: bool) -> int:
    return weekday(s, d1904) - 1


@fn("NETWORKDAYS", 2, 3)
def f_networkdays(ctx: Any, a: Any, b: Any, h: Any = None) -> float:
    return _networkdays(ctx, a, b, h, {0, 6}, True)


@fn("NETWORKDAYS.INTL", 2, 4)
def f_networkdays_intl(ctx: Any, a: Any, b: Any, w: Any = None, h: Any = None) -> float:
    return _networkdays(ctx, a, b, h, _weekend_set(ctx, w), False)


def _networkdays(ctx: Any, a: Any, b: Any, h: Any, weekend_sun0: Any, sun_first: bool) -> float:
    d1904 = _d1904(ctx)
    s, e = math.floor(_serial_arg(ctx, a)), math.floor(_serial_arg(ctx, b))
    hol = _holidays(ctx, h)
    sign = 1
    if s > e:
        s, e, sign = e, s, -1
    n = 0
    for d in range(s, e + 1):
        w = weekday(d, d1904) - 1  # Sunday = 0
        wmon = (w - 1) % 7  # Monday = 0
        off = (w in weekend_sun0) if sun_first else (wmon in weekend_sun0)
        if not off and d not in hol:
            n += 1
    return float(sign * n)


@fn("WORKDAY", 2, 3)
def f_workday(ctx: Any, a: Any, days: Any, h: Any = None) -> float:
    return _workday(ctx, a, days, h, {0, 6}, True)


@fn("WORKDAY.INTL", 2, 4)
def f_workday_intl(ctx: Any, a: Any, days: Any, w: Any = None, h: Any = None) -> float:
    return _workday(ctx, a, days, h, _weekend_set(ctx, w), False)


def _workday(ctx: Any, a: Any, days: Any, h: Any, weekend: Any, sun_first: bool) -> float:
    d1904 = _d1904(ctx)
    cur = math.floor(_serial_arg(ctx, a))
    n = integer(ctx, days)
    hol = _holidays(ctx, h)
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        cur += step
        w = weekday(cur, d1904) - 1
        off = (w in weekend) if sun_first else (((w - 1) % 7) in weekend)
        if not off and cur not in hol:
            left -= 1
    return float(cur)


@fn("WEEKNUM", 1, 2)
def f_weeknum(ctx: Any, a: Any, t: Any = None) -> float:
    s = _serial_arg(ctx, a)
    y, _m, _d = serial_to_ymd(s, _d1904(ctx))
    kind = int(opt_num(ctx, t, 1))
    jan1 = ymd_to_serial(y, 1, 1, _d1904(ctx))
    assert jan1 is not None
    w1 = weekday(jan1, _d1904(ctx))  # 1 = Sunday
    start = 1 if kind == 1 else 2 if kind in (2, 11) else None
    if kind == 21:
        return f_isoweeknum(ctx, a)
    if start is None:
        raise XlRaise(E.NUM)
    offset = (w1 - start) % 7
    return float((math.floor(s) - jan1 + offset) // 7 + 1)


@fn("ISOWEEKNUM", 1, 1)
def f_isoweeknum(ctx: Any, a: Any) -> float:
    y, m, d = serial_to_ymd(_serial_arg(ctx, a), _d1904(ctx))
    return float(date(y, m, d).isocalendar()[1])


@fn("YEARFRAC", 2, 3)
def f_yearfrac(ctx: Any, a: Any, b: Any, basis: Any = None) -> float:
    s, e = _serial_arg(ctx, a), _serial_arg(ctx, b)
    if s > e:
        s, e = e, s
    bs = int(opt_num(ctx, basis, 0))
    s, e = math.floor(s), math.floor(e)
    if bs in (0, 4):
        y1, m1, d1 = serial_to_ymd(s, _d1904(ctx))
        y2, m2, d2 = serial_to_ymd(e, _d1904(ctx))
        if bs == 0:
            if d1 == days_in_month(y1, m1) and m1 == 2:
                d1 = 30
            if d1 == 31:
                d1 = 30
            if d2 == 31 and d1 >= 30:
                d2 = 30
        else:
            d1, d2 = min(d1, 30), min(d2, 30)
        return ((y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)) / 360
    if bs == 2:
        return (e - s) / 360
    if bs == 3:
        return (e - s) / 365
    if bs == 1:
        y1, _, _ = serial_to_ymd(s, _d1904(ctx))
        y2, _, _ = serial_to_ymd(e, _d1904(ctx))
        if y1 == y2:
            return (e - s) / (366 if is_leap(y1) else 365)
        total = sum(366 if is_leap(y) else 365 for y in range(y1, y2 + 1))
        return (e - s) / (total / (y2 - y1 + 1))
    raise XlRaise(E.NUM)


# -- explicit calendar functions: work in every mode -------------------------------------------------------
def _explicit(prefix: str, cal: str) -> None:
    @fn(f"{prefix}YEAR", 1, 1)
    def _y(ctx: Any, a: Any) -> float:
        return float(serial_to_cal(math.floor(_serial_arg(ctx, a)), cal, _d1904(ctx))[0])

    @fn(f"{prefix}MONTH", 1, 1)
    def _m(ctx: Any, a: Any) -> float:
        return float(serial_to_cal(math.floor(_serial_arg(ctx, a)), cal, _d1904(ctx))[1])

    @fn(f"{prefix}DAY", 1, 1)
    def _d(ctx: Any, a: Any) -> float:
        return float(serial_to_cal(math.floor(_serial_arg(ctx, a)), cal, _d1904(ctx))[2])

    @fn(f"{prefix}DATE", 3, 3)
    def _date(ctx: Any, y: Any, m: Any, d: Any) -> float:
        base = cal_to_serial(integer(ctx, y), integer(ctx, m), 1, cal, _d1904(ctx))
        if base is None:
            raise XlRaise(E.NUM)
        s = base + (integer(ctx, d) - 1)
        if s < 0 or s > 2958465:
            raise XlRaise(E.NUM)
        return s


_explicit("J", "jalali")  # JYEAR JMONTH JDAY JDATE
_explicit("H", "hijri")  # HYEAR HMONTH HDAY HDATE
