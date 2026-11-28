"""Formulas on realistic, messy sheets. The expected values are what Excel gives (checked case by case);
the first block covers the two behaviours this file's commit changed."""
from __future__ import annotations

import datetime as dt

import pytest

from .envkit import DictEnv, ev, show


def serial(y: int, m: int, d: int) -> int:
    return (dt.date(y, m, d) - dt.date(1899, 12, 30)).days


# ---------------------------------------------------------------------- numbers are compared at 15 digits
@pytest.mark.parametrize("formula,expected", [
    ("0.1+0.2=0.3", True), ("0.1*3=0.3", True), ("(0.1+0.2)*10=3", True), ("SQRT(2)^2=2", True),
    ("(0.1+0.2)<>0.3", False), ("0.1+0.2>0.3", False), ("0.1+0.2<0.3", False), ("0.1+0.2>=0.3", True),
    ("0.1+0.2<=0.3", True), ("0.30000000000001=0.3", False), ("0.3<0.30000000000001", True),
    ("1=1.1", False), ("IF(0.1+0.2=0.3,\"same\",\"diff\")", "same"),
])
def test_equality_and_ordering_use_15_significant_digits(formula: str, expected: object) -> None:
    assert show(ev(formula)) == expected


def test_lookups_and_criteria_agree_with_the_equals_operator() -> None:
    env = DictEnv({(0, 0, 0): 0.1 + 0.2, (0, 1, 0): 0.3, (0, 2, 0): 0.30000000000000004, (0, 3, 0): 0.31,
                   (0, 0, 1): 1, (0, 1, 1): 2, (0, 2, 1): 4, (0, 3, 1): 8})
    expect = {
        "COUNTIF(A1:A4,0.3)": 3, 'COUNTIF(A1:A4,"=0.3")': 3, 'COUNTIF(A1:A4,"<>0.3")': 1, 'COUNTIF(A1:A4,">0.3")': 1,
        'COUNTIF(A1:A4,"<=0.3")': 3, 'COUNTIF(A1:A4,">=0.3")': 4, "SUMIF(A1:A4,0.3,B1:B4)": 7,
        'SUMIF(A1:A4,">0.3",B1:B4)': 8, "MATCH(0.3,A1:A4,0)": 1, "VLOOKUP(0.3,A1:B4,2,FALSE)": 1,
        "XLOOKUP(0.3,A1:A4,B1:B4)": 1, "MAXIFS(B1:B4,A1:A4,0.3)": 4,
    }
    for formula, value in expect.items():
        assert show(ev(formula, env, array=True)) == value, formula


def test_numbers_that_really_differ_stay_different() -> None:
    assert show(ev("1000000000000001=1000000000000000")) is True  # 16 digits: equal at 15, as in Excel
    assert show(ev("0.1234567890123=0.1234567890124")) is False  # they differ in the 13th digit
    assert show(ev("ROUND(0.1+0.2,14)=0.3")) is True


# ---------------------------------------------------------------------- dates written with month names
@pytest.mark.parametrize("text,expected", [
    ("5-Mar-2024", serial(2024, 3, 5)), ("5-Mar-24", serial(2024, 3, 5)), ("5-Mar-45", serial(1945, 3, 5)),
    ("Mar 5, 2024", serial(2024, 3, 5)), ("5 Mar 2024", serial(2024, 3, 5)), ("March 5, 2024", serial(2024, 3, 5)),
    ("5 MARCH 2024", serial(2024, 3, 5)), ("sept 9 2024", serial(2024, 9, 9)), ("March 2024", serial(2024, 3, 1)),
    ("29 Feb 2024", serial(2024, 2, 29)),
    ("29 Feb 2023", "#VALUE!"), ("31 Apr 2024", "#VALUE!"), ("5 Foo 2024", "#VALUE!"), ("5 Mar", "#VALUE!"),
    ("Mar 5", "#VALUE!"), ("32 Mar 2024", "#VALUE!"),
])
def test_datevalue_reads_english_month_names(text: str, expected: object) -> None:
    assert show(ev(f'DATEVALUE("{text}")')) == expected
    assert show(ev(f'DAY("{text}")')) == (expected if expected == "#VALUE!" else (dt.date(1899, 12, 30) + dt.timedelta(expected)).day)


@pytest.mark.parametrize("cal", ["jalali", "hijri", "gregorian"])
def test_month_names_are_gregorian_in_every_calendar_mode_and_jalali_text_follows_the_mode(cal: str) -> None:
    from gridora_engine.formula.functions.datefn import parse_date_text

    assert parse_date_text("5 March 2024", False, cal) == serial(2024, 3, 5)
    assert parse_date_text("Mar 5, 2024", False, cal) == serial(2024, 3, 5)
    jalali = parse_date_text("1403/01/01", False, cal)
    assert jalali == (serial(2024, 3, 20) if cal == "jalali" else jalali)  # Nowruz 1403; other modes read their own calendar


def test_numeric_text_dates_still_work_and_a_leading_text_word_is_not_a_date() -> None:
    assert show(ev('DATEVALUE("2024-03-05")')) == serial(2024, 3, 5)
    assert show(ev('DATEVALUE("3/5/2024")')) == serial(2024, 3, 5)
    assert show(ev('DATEVALUE("hello world")')) == "#VALUE!"


# ---------------------------------------------------------------------- behaviours checked against Excel (guards)
SHEET = DictEnv({
    (0, 0, 0): "a", (0, 1, 0): "A", (0, 2, 0): "b", (0, 3, 0): "ab c", (0, 4, 0): None, (0, 5, 0): "a1",
    (0, 0, 1): 1, (0, 1, 1): 2, (0, 2, 1): 3, (0, 3, 1): 4, (0, 4, 1): 5, (0, 5, 1): 6,
    (0, 0, 2): 10, (0, 1, 2): 20, (0, 2, 2): None, (0, 3, 2): "5", (0, 4, 2): 40, (0, 5, 2): "abc",
    (0, 0, 3): "x", (0, 1, 3): "y", (0, 2, 3): "x", (0, 3, 3): "z", (0, 4, 3): None, (0, 5, 3): "",
})


@pytest.mark.parametrize("formula,expected", [
    ("ROUND(2.5,0)", 3), ("ROUND(-2.5,0)", -3), ("ROUND(1.005,2)", 1.01), ("ROUND(2.675,2)", 2.68),
    ("ROUND(1234.5678,-2)", 1200), ("MOD(-7,3)", 2), ("MOD(7,-3)", -2), ("MOD(5,0)", "#DIV/0!"), ("INT(-1.5)", -2),
    ("TRUNC(-1.5)", -1), ("POWER(0,0)", "#NUM!"), ("QUOTIENT(-7,2)", -3), ("FLOOR(-2.5,-2)", -2),
    ("SUM(C1:C6)", 70), ("COUNT(B1:C6)", 9), ("COUNTA(A1:D6)", 21), ("AVERAGE(C1:C6)", 70 / 3),
    ('SUM("3",2)', 5), ('SUM(B1:B3,"x")', "#VALUE!"), ("MAX(C1:C3)", 20), ("MEDIAN(B1:B6)", 3.5),
    ('SUMIF(A1:A6,"a",B1:B6)', 3), ('SUMIF(A1:A6,"a*",B1:B6)', 13), ('SUMIF(A1:A6,"<>a",B1:B6)', 18),
    ('COUNTIF(A1:A6,"?")', 3), ('COUNTIF(D1:D6,"")', 2), ('COUNTIF(C1:C6,"5")', 1), ('COUNTIF(A1:A6,">3")', 0),
    ('COUNTIFS(B1:B6,">1",D1:D6,"x")', 1), ('SUMIFS(B1:B6,D1:D6,"x",B1:B6,">1")', 3),
    ('VLOOKUP("B",A1:C6,2,FALSE)', 3), ('VLOOKUP("a*",A1:C6,2,FALSE)', 1), ('VLOOKUP(2.5,B1:C6,2,TRUE)', 20),
    ('VLOOKUP("zz",A1:C6,2,FALSE)', "#N/A"), ('MATCH("x",D1:D6,0)', 1), ('XLOOKUP("q",A1:A6,B1:B6,"none")', "none"),
    ('LEFT("علی رضا",3)', "علی"), ('MID("علی رضا",5,4)', "رضا"), ('TRIM("  a   b  ")', "a b"),
    ('LEN(TRIM("a"&CHAR(160)&"b"))', 3), ('VALUE("1,234.5")', 1234.5), ('VALUE("12%")', 0.12), ('VALUE("(5)")', -5),
    ('NUMBERVALUE("1.234,5",",",".")', 1234.5), ('TEXT(1234.5,"#,##0.00")', "1,234.50"), ('TEXT(0.256,"0.0%")', "25.6%"),
    ('"x"&(0.1+0.2)', "x0.3"), ('TEXTJOIN(",",TRUE,A1:A6)', "a,A,b,ab c,a1"), ('"3"+4', 7), ('"a"+1', "#VALUE!"),
    ('""+0', "#VALUE!"), ('"a"="A"', True), ('"علی"="علي"', False), ("A5=0", True), ('A5=""', True),
    ("DATE(2024,2,30)", serial(2024, 3, 1)), ("DATE(2024,14,1)", serial(2025, 2, 1)), ("DATE(2024,1,0)", serial(2023, 12, 31)),
    ("DATE(1900,2,29)", 60), ("EDATE(DATE(2024,1,31),1)", serial(2024, 2, 29)), ("EOMONTH(DATE(2024,1,15),-2)", serial(2023, 11, 30)),
    ('DATEDIF(DATE(2020,5,10),DATE(2024,3,5),"ym")', 9), ('DATEDIF(DATE(2020,5,10),DATE(2024,3,5),"md")', 24),
    ('DATEDIF(DATE(2021,1,1),DATE(2020,1,1),"d")', "#NUM!"), ("NETWORKDAYS(DATE(2024,3,11),DATE(2024,3,17))", 5),
    ("DAYS360(DATE(2024,1,31),DATE(2024,3,1))", 31), ("ISOWEEKNUM(DATE(2021,1,3))", 53), ("WEEKDAY(DATE(2024,3,17),2)", 7),
    ('IF("TRUE",1,2)', 1), ('IF("",1,2)', "#VALUE!"), ('AND(1,"x")', "#VALUE!"), ("IFNA(1/0,8)", "#DIV/0!"),
    ("IFS(FALSE,1)", "#N/A"), ('SWITCH(9,1,"a")', "#N/A"), ("TRUE+1", 2), ("ISNUMBER(\"1\")", False), ("TYPE(1/0)", 16),
])
def test_results_match_excel_on_messy_data(formula: str, expected: object) -> None:
    got = show(ev(formula, SHEET))
    if isinstance(expected, float):
        assert got == pytest.approx(expected), formula
    else:
        assert got == expected, formula


def test_a_plain_range_expression_needs_array_context_exactly_like_legacy_excel() -> None:
    """Known limit (ROADMAP item 8): outside an array formula a multi-cell operand is intersected with the
    formula's own row/column, so SUM(B1:B6*2) typed in a cell is not the dynamic-array answer. Inside array
    context (array formulas, LET/LAMBDA bodies) it is. This test records both so a change is deliberate."""
    assert show(ev("SUM(B1:B6*2)", SHEET, array=True)) == 42
    assert show(ev("SUM(IF(B1:B6>2,B1:B6,0))", SHEET, array=True)) == 18
    assert show(ev("SUMPRODUCT((D1:D6=\"x\")*B1:B6)", SHEET)) == 4  # SUMPRODUCT always evaluates its arguments as arrays
