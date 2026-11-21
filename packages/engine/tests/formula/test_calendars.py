from __future__ import annotations

import pytest

from .envkit import DictEnv, ev, show


class CalEnv(DictEnv):
    def __init__(self, calendar):
        super().__init__()
        self.calendar = calendar


J, G, H = CalEnv("jalali"), CalEnv("gregorian"), CalEnv("hijri")
NOWRUZ_1403 = 45371.0  # 2024-03-20

CASES = [
    (J, "YEAR(45371)", 1403.0), (J, "MONTH(45371)", 1.0), (J, "DAY(45371)", 1.0),
    (J, "DATE(1403,1,1)", NOWRUZ_1403), (J, "DATE(1402,12,29)", NOWRUZ_1403 - 1),
    (J, "DATE(1403,13,1)", NOWRUZ_1403 + 366), (J, "DATE(1403,1,32)", NOWRUZ_1403 + 31),
    (J, "DATE(1403,2,0)", NOWRUZ_1403 + 30), (J, "YEAR(DATE(3,1,1))", 1303.0),
    (J, "DAY(EDATE(DATE(1403,6,31),1))", 30.0),
    (J, "MONTH(EOMONTH(DATE(1403,12,5),0))", 12.0), (J, "DAY(EOMONTH(DATE(1403,12,5),0))", 30.0),
    (J, "DAY(EOMONTH(DATE(1404,12,5),0))", 29.0), (J, "DAY(EOMONTH(DATE(1403,7,5),0))", 30.0),
    (J, 'DATEVALUE("1403/01/01")', NOWRUZ_1403), (J, 'DATEVALUE("۱۴۰۳/۰۱/۰۱")', NOWRUZ_1403),
    (J, 'DATEVALUE("2024-03-20")', NOWRUZ_1403), (J, 'VALUE("1403-1-1")', NOWRUZ_1403),
    (J, 'DATEDIF(DATE(1400,1,1),DATE(1403,7,1),"Y")', 3.0), (J, 'DATEDIF(DATE(1400,1,1),DATE(1403,7,1),"YM")', 6.0),
    (J, 'TEXT(45371,"yyyy/mm/dd")', "1403/01/01"), (J, 'TEXT(45371,"d mmmm yyyy")', "1 فروردین 1403"),
    (J, 'TEXT(45371,"dddd")', "چهارشنبه"),
    (G, "YEAR(45371)", 2024.0), (G, 'TEXT(45371,"yyyy-mm-dd")', "2024-03-20"),
    (G, 'DATEVALUE("2024/03/20")', NOWRUZ_1403),
    (H, "YEAR(45371)", 1445.0), (H, "MONTH(45371)", 9.0), (H, 'TEXT(45371,"mmmm")', "رمضان"),
    (H, "DATE(1445,9,10)", NOWRUZ_1403),
    # explicit functions work in every mode
    (G, "JYEAR(45371)", 1403.0), (G, "JMONTH(45371)", 1.0), (G, "JDAY(45371)", 1.0), (G, "JDATE(1403,1,1)", NOWRUZ_1403),
    (J, "HYEAR(45371)", 1445.0), (G, "HDATE(1445,9,10)", NOWRUZ_1403),
]


@pytest.mark.parametrize("env,formula,expected", CASES, ids=[f"{e.calendar}:{f}" for e, f, _ in CASES])
def test_calendar_cases(env, formula, expected):
    got = show(ev(formula, env))
    assert got == expected, (formula, got)


def test_jalali_leap_years_and_month_lengths():
    # 1403 is leap (Esfand has 30 days), 1404 is not
    assert ev("DATE(1404,1,1)-DATE(1403,1,1)", J) == 366.0
    assert ev("DATE(1405,1,1)-DATE(1404,1,1)", J) == 365.0
    assert ev("DAY(DATE(1403,7,0))", J) == 31.0  # day 0 = last day of month 6 (31 days)
