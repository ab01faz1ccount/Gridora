from __future__ import annotations

import math

import pytest

from .envkit import DictEnv, ev, show

DATA = DictEnv({
    (0, 0, 0): "Bob", (0, 1, 0): "Ann", (0, 2, 0): "Cy", (0, 3, 0): "apple",
    (0, 0, 1): 10.0, (0, 1, 1): 20.0, (0, 2, 1): 30.0, (0, 3, 1): 4.0,
    (0, 0, 2): 1.0, (0, 1, 2): 2.0, (0, 2, 2): 3.0,
})

# (formula, expected). Floats compared with a tolerance. Expected values are Excel's.
CASES = [
    # arithmetic, coercion, precedence
    ("1+2*3", 7.0), ("-2^2", 4.0), ("2^3^2", 64.0), ("50%+1", 1.5), ('"5"+1', 6.0), ("TRUE+1", 2.0),
    ('"a"&1&TRUE', "a1TRUE"), ("1/0", "#DIV/0!"), ('"abc"+1', "#VALUE!"), ("0^0", "#NUM!"),
    ("(-8)^(1/3)", "#NUM!"), ('"A"="a"', True), ("1<2", True), ('"a"<"b"', True), ('1<"a"', True),
    ('TRUE>"z"', True), ("A5=0", True), ('A5=""', True),
    # logical
    ('IF(1>0,"y","n")', "y"), ("IF(FALSE,1)", False), ('IFERROR(1/0,"e")', "e"), ("IFNA(NA(),7)", 7.0),
    ("IFS(FALSE,1,TRUE,2)", 2.0), ("IFS(FALSE,1)", "#N/A"), ("AND(TRUE,1)", True), ("OR(FALSE,0)", False),
    ("XOR(TRUE,TRUE,TRUE)", True), ("NOT(0)", True), ('SWITCH(2,1,"a",2,"b","z")', "b"),
    ('SWITCH(9,1,"a","z")', "z"), ('CHOOSE(2,"a","b")', "b"),
    # math
    ("SUM(B1:B4)", 64.0), ('SUM(B1:B4,"5")', 69.0), ("SUM(A1:A4)", 0.0), ("PRODUCT(C1:C3)", 6.0),
    ("ROUND(2.675,2)", 2.68), ("ROUND(-2.5,0)", -3.0), ("ROUND(1234.5,-2)", 1200.0),
    ("ROUNDUP(-1.01,1)", -1.1), ("ROUNDDOWN(-2.55,1)", -2.5), ("MOD(-3,2)", 1.0), ("MOD(3,-2)", -1.0),
    ("MOD(1,0)", "#DIV/0!"), ("INT(-1.5)", -2.0), ("TRUNC(-1.567,2)", -1.56), ("ABS(-3)", 3.0),
    ("SQRT(-1)", "#NUM!"), ("POWER(2,10)", 1024.0), ("LOG(8,2)", 3.0), ("LOG10(1000)", 3.0),
    ("EXP(0)", 1.0), ("LN(1)", 0.0), ("FACT(5)", 120.0), ("COMBIN(5,2)", 10.0), ("GCD(12,18)", 6.0),
    ("LCM(4,6)", 12.0), ("CEILING(2.1,0.5)", 2.5), ("FLOOR(3.7,0.5)", 3.5), ("EVEN(3)", 4.0),
    ("ODD(2)", 3.0), ("MROUND(10,3)", 9.0), ("SIGN(-4)", -1.0), ("PI()", math.pi),
    ("SUMPRODUCT(C1:C3,C1:C3)", 14.0), ("SUMPRODUCT((B1:B3>10)*(C1:C3))", 5.0),
    ("MDETERM({1,2;3,4})", -2.0), ("SUM(MMULT({1,2;3,4},{1;1}))", 10.0),
    ("SUM(MINVERSE({2,0;0,4}))", 0.75), ("SUBTOTAL(9,B1:B3)", 60.0), ("SUBTOTAL(1,B1:B3)", 20.0),
    ("SUM(SEQUENCE(4))", 10.0), ("SUM(TRANSPOSE({1,2,3}))", 6.0),
    # stats
    ("AVERAGE(B1:B4)", 16.0), ("AVERAGE(A1:A4)", "#DIV/0!"), ("MAX(B1:B4)", 30.0), ("MIN(B1:B4)", 4.0),
    ("MAX(A1:A4)", 0.0), ("COUNT(A1:B4)", 4.0), ("COUNTA(A1:B4)", 8.0), ("COUNTBLANK(A1:C4)", 1.0),
    ("MEDIAN(B1:B4)", 15.0), ("LARGE(B1:B4,2)", 20.0), ("SMALL(B1:B4,1)", 4.0), ("RANK(20,B1:B4)", 2.0),
    ("STDEV(B1:B4)", math.sqrt(392 / 3)), ("VAR(C1:C3)", 1.0), ("STDEVP(C1:C3)", math.sqrt(2 / 3)),
    ("PERCENTILE(B1:B4,0.5)", 15.0), ("QUARTILE(B1:B4,1)", 8.5), ("CORREL(C1:C3,B1:B3)", 1.0),
    ("SLOPE(B1:B3,C1:C3)", 10.0), ("INTERCEPT(B1:B3,C1:C3)", 0.0), ("FORECAST(4,B1:B3,C1:C3)", 40.0),
    ("MODE({1,2,2,3})", 2.0), ("GEOMEAN({1,4})", 2.0), ("DEVSQ({1,2,3})", 2.0),
    ('COUNTIF(A1:A4,"a*")', 2.0), ('COUNTIF(A1:A4,"?n?")', 1.0), ('COUNTIF(B1:B4,">5")', 3.0),
    ('COUNTIF(B1:B4,"<>10")', 3.0), ("COUNTIF(B1:B4,20)", 1.0), ('SUMIF(B1:B4,">5")', 60.0),
    ('SUMIF(A1:A4,"Ann",B1:B4)', 20.0), ('SUMIFS(B1:B4,A1:A4,"<>Ann",B1:B4,">5")', 40.0),
    ('COUNTIFS(B1:B4,">5",B1:B4,"<25")', 2.0), ('AVERAGEIF(B1:B4,">=10")', 20.0),
    ('MAXIFS(B1:B4,B1:B4,"<30")', 20.0), ('MINIFS(B1:B4,B1:B4,">4")', 10.0),
    ("NORM.S.DIST(0,TRUE)", 0.5), ("NORM.S.INV(0.5)", 0.0),
    # lookup
    ('VLOOKUP("Ann",A1:C3,2,FALSE)', 20.0), ('VLOOKUP("B*",A1:B3,2,0)', 10.0), ('VLOOKUP("zz",A1:B3,2,0)', "#N/A"),
    ("VLOOKUP(25,B1:C3,2)", 2.0), ('VLOOKUP("Ann",A1:B3,3,0)', "#REF!"), ('MATCH("Cy",A1:A3,0)', 3.0),
    ("MATCH(25,B1:B3,1)", 2.0), ("MATCH(5,B1:B3,1)", "#N/A"), ("INDEX(B1:B3,2)", 20.0),
    ("INDEX(A1:C3,2,3)", 2.0), ("SUM(INDEX(B1:B3,1):INDEX(B1:B3,3))", 60.0), ("INDEX(B1:B3,5)", "#REF!"),
    ('XLOOKUP("Cy",A1:A3,B1:B3)', 30.0), ('XLOOKUP("Zed",A1:A3,B1:B3,"none")', "none"),
    ("XLOOKUP(25,B1:B3,A1:A3,,-1)", "Ann"), ("XMATCH(20,B1:B3)", 2.0), ("LOOKUP(25,B1:B3,A1:A3)", "Ann"),
    ("OFFSET(A1,1,1)", 20.0), ('INDIRECT("B2")', 20.0), ('SUM(INDIRECT("B1:B3"))', 60.0),
    ('INDIRECT("Nope!A1")', "#REF!"), ("ADDRESS(3,2)", "$B$3"), ("ADDRESS(3,2,4)", "B3"),
    ("SUM(SORT({3;1;2}))", 6.0), ("INDEX(SORT({3;1;2}),1)", 1.0), ("ROWS(UNIQUE({1;1;2}))", 2.0),
    ("ROWS(FILTER({1;2;3},{1;0;1}))", 2.0), ("ROW(B3)", 3.0), ("COLUMN(C1)", 3.0), ("ROWS(A:A)", 1048576.0),
    ("COLUMNS(A1:C2)", 3.0),
    # text
    ('LEFT("hello",2)', "he"), ('RIGHT("hello",3)', "llo"), ('MID("hello",2,3)', "ell"), ('LEN("héllo")', 5.0),
    ('UPPER("a")&LOWER("B")', "Ab"), ('PROPER("hello wORLD")', "Hello World"), ('TRIM("  a   b ")', "a b"),
    ('SUBSTITUTE("a-b-c","-","+",2)', "a-b+c"), ('REPLACE("abcdef",2,3,"X")', "aXef"),
    ('FIND("l","hello")', 3.0), ('FIND("z","hello")', "#VALUE!"), ('SEARCH("L*o","hello")', 3.0),
    ('REPT("ab",3)', "ababab"), ('EXACT("a","A")', False), ('VALUE("1,234.5")', 1234.5),
    ('TEXTJOIN(", ",TRUE,A1:A3)', "Bob, Ann, Cy"), ('CONCAT(A1:A2,"!")', "BobAnn!"), ('CODE("A")', 65.0),
    ("CHAR(66)", "B"), ("UNICODE(\"ا\")", 1575.0), ('TEXTBEFORE("a-b-c","-",2)', "a-b"),
    ('TEXTAFTER("a-b-c","-")', "b-c"), ('NUMBERVALUE("1.234,5",",",".")', 1234.5),
    # TEXT formats
    ('TEXT(1234.567,"#,##0.00")', "1,234.57"), ('TEXT(0.256,"0.0%")', "25.6%"), ('TEXT(5,"000")', "005"),
    ('TEXT(1234567,"0.00E+00")', "1.23E+06"), ('TEXT(0,"#")', ""), ('TEXT(-3,"0;(0)")', "(3)"),
    ('TEXT(1500000,"#,##0,,\\M")', "2M"), ('TEXT(1,"General")', "1"),
    ('TEXT(DATE(2024,5,3),"yyyy-mm-dd")', "2024-05-03"), ('TEXT(DATE(2024,5,3),"dddd, mmmm d")', "Friday, May 3"),
    ('TEXT(DATE(2024,5,3)+0.75,"hh:mm:ss")', "18:00:00"), ('TEXT(0.5,"h:mm AM/PM")', "12:00 PM"),
    ('TEXT(DATE(2024,5,3),"d/m/yy")', "3/5/24"),
    # dates
    ("DATE(2024,2,29)", 45351.0), ("DATE(1900,2,29)", 60.0), ("DATE(1900,3,1)", 61.0),
    ("DATE(2024,13,1)", 45658.0), ("DAY(DATE(2024,3,0))", 29.0), ("YEAR(45000)", 2023.0),
    ("MONTH(45000)", 3.0), ("WEEKDAY(DATE(2024,5,15))", 4.0), ("WEEKDAY(DATE(2024,5,15),2)", 3.0),
    ("EDATE(DATE(2024,1,31),1)", 45351.0), ("EOMONTH(DATE(2024,1,15),1)", 45351.0),
    ('DATEDIF(DATE(2020,1,15),DATE(2024,3,10),"Y")', 4.0), ('DATEDIF(DATE(2020,1,15),DATE(2024,3,10),"YM")', 1.0),
    ('DATEDIF(DATE(2020,1,15),DATE(2024,3,10),"MD")', 24.0), ("NETWORKDAYS(DATE(2024,5,1),DATE(2024,5,31))", 23.0),
    ("WORKDAY(DATE(2024,5,3),3)", 45420.0), ("ISOWEEKNUM(DATE(2024,1,1))", 1.0),
    ('DATEVALUE("2024-05-15")', 45427.0), ("DAYS(DATE(2024,3,1),DATE(2024,2,1))", 29.0),
    ("HOUR(0.75)", 18.0), ("TIME(13,30,0)", 0.5625), ("TODAY()", 46000.0), ("NOW()", 46000.5),
    ("YEARFRAC(DATE(2024,1,1),DATE(2024,7,1))", 0.5),
    # info
    ("ISNUMBER(B1)", True), ("ISTEXT(A1)", True), ("ISBLANK(Z9)", True), ("ISERROR(1/0)", True),
    ("ISNA(NA())", True), ("ISERR(NA())", False), ("ISEVEN(4)", True), ("N(TRUE)", 1.0), ('T(5)', ""),
    ("TYPE(A1)", 2.0), ("ERROR.TYPE(1/0)", 2.0), ("NOPE(1)", "#NAME?"), ("MyName", "#NAME?"),
    # financial
    ("PMT(0.05/12,60,-20000)", 377.4246728802198), ("FV(0.05,10,-100)", 1257.789253554884),
    ("PV(0.05,10,-100)", 772.1734929184812), ("NPV(0.1,100,100)", 173.55371900826447),
    ("IRR({-100,60,60})", 0.13066238629180746), ("IPMT(0.1,1,2,1000)", -100.0),
    ("PPMT(0.1,1,2,1000)", -476.1904761904762), ("SLN(1000,100,9)", 100.0), ("NPER(0.1,-200,1000)", 7.2725408973),
]


@pytest.mark.parametrize("formula,expected", CASES, ids=[c[0] for c in CASES])
def test_formula(formula, expected):
    got = show(ev(formula, DATA, (0, 20, 20)))
    if isinstance(expected, float) and isinstance(got, float):
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-9)
    else:
        assert got == expected


def test_function_registry_size():
    from gridora_engine.formula.functions import REGISTRY

    assert len(REGISTRY) >= 200
