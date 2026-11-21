from __future__ import annotations

import pytest

from .envkit import DictEnv, ev, show


def _env():
    cells = {}
    tbl = [["Tree", "Height", "Age", "Yield"], ["Apple", 18, 20, 14], ["Pear", 12, 12, 10], ["Cherry", 13, 14, 9],
           ["Apple", 14, 15, 10], ["Pear", 9, 8, 8], ["Apple", 8, 9, 6]]
    for i, r in enumerate(tbl):
        for j, v in enumerate(r):
            cells[(0, i, j)] = v
    for i, r in enumerate([["Tree", "Height", "Height"], ["=Apple", ">10", "<16"], ["=Pear", None, None]]):
        for j, v in enumerate(r):
            if v is not None:
                cells[(0, i, 6 + j)] = v
    for i, v in enumerate([79, 85, 78, 85, 50, 81, 95, 88, 97]):
        cells[(0, i, 10)] = float(v)
    for i, v in enumerate([70, 79, 89]):
        cells[(0, i, 11)] = float(v)
    for i, v in enumerate([-120000., 39000., 30000., 21000., 37000., 46000.]):
        cells[(0, i, 13)] = v
    for i, v in enumerate([-10000., 2750., 4250., 3250., 2750.]):
        cells[(0, i, 14)] = v
    for i, v in enumerate([39448., 39508., 39751., 39859., 39904.]):
        cells[(0, i, 15)] = v
    return DictEnv(cells)


ENV = _env()
# Values are Microsoft's documented results unless noted.
CASES = [
    ("ERF(1)", 0.8427007929), ("ERFC(1)", 0.1572992071), ("ROMAN(1999)", "MCMXCIX"), ('ARABIC("MCMXCIX")', 1999.0),
    ("BASE(255,16,4)", "00FF"), ('DECIMAL("FF",16)', 255.0), ("BITAND(13,25)", 9.0), ("BITOR(13,25)", 29.0),
    ("BITXOR(13,25)", 20.0), ("BITLSHIFT(4,2)", 16.0), ("BITRSHIFT(16,2)", 4.0),
    ("DEC2BIN(9,4)", "1001"), ("DEC2BIN(-100)", "1110011100"), ("DEC2HEX(255)", "FF"), ("DEC2HEX(-1)", "FFFFFFFFFF"),
    ("BIN2DEC(1111111111)", -1.0), ("BIN2DEC(1100100)", 100.0), ('HEX2BIN("F",8)', "00001111"), ('BIN2HEX("11111011")', "FB"),
    ("DEC2OCT(58)", "72"), ('CONVERT(1,"lbm","kg")', 0.45359237), ('CONVERT(68,"F","C")', 20.0), ('CONVERT(2.5,"ft","sec")', "#N/A"),
    ('CONVERT(1,"km","mi")', 0.6213711922), ("SUM(MUNIT(3))", 3.0), ("DELTA(5,4)", 0.0), ("GESTEP(5,4)", 1.0),
    ("RRI(96,10000,11000)", 0.0009933074), ("EFFECT(0.0525,4)", 0.0535426674), ("NOMINAL(0.053543,4)", 0.0525003199),
    ("SYD(30000,7500,10,1)", 4090.909090909), ("DB(1000000,100000,6,1,7)", 186083.33333), ("DB(1000000,100000,6,2,7)", 259639.41667),
    ("DB(1000000,100000,6,7,7)", 15845.098474), ("DDB(2400,300,10,1,2)", 480.0), ("DDB(2400,300,10,10)", 22.1225472),
    ("VDB(2400,300,120,6,18,1.5)", 311.8089367), ("MIRR(N1:N6,0.1,0.12)", 0.1260941304), ("XNPV(0.09,O1:O5,P1:P5)", 2086.647602),
    ("XIRR(O1:O5,P1:P5)", 0.3733625335), ("CUMIPMT(0.09/12,360,125000,13,24,0)", -11135.23213),
    ("CUMPRINC(0.09/12,360,125000,13,24,0)", -934.1071234), ("CUMIPMT(0.09/12,360,125000,1,1,1)", 0.0),
    ('DSUM(A1:D7,"Yield",G1:H2)', 24.0), ('DSUM(A1:D7,"Yield",G1:I3)', 28.0), ("DCOUNT(A1:D7,\"Age\",G1:H2)", 2.0),
    ('DGET(A1:D7,"Yield",G1:G3)', "#NUM!"), ('DMAX(A1:D7,"Nope",G1:H2)', "#VALUE!"),
    ("ROWS(TAKE(A1:D7,2,3))", 2.0), ("INDEX(TAKE(A1:D7,-1),1,1)", "Apple"), ("COLUMNS(DROP(A1:D7,1,1))", 3.0),
    ("INDEX(CHOOSECOLS(A1:D7,-1),2)", 14.0), ("ROWS(TOCOL(A1:B2))", 4.0), ("INDEX(WRAPROWS(TOCOL(B2:B7),3),2,1)", 14.0),
    ("INDEX(FREQUENCY(K1:K9,L1:L3),1)", 1.0), ("INDEX(FREQUENCY(K1:K9,L1:L3),2)", 2.0), ("INDEX(FREQUENCY(K1:K9,L1:L3),3)", 4.0),
    ("INDEX(FREQUENCY(K1:K9,L1:L3),4)", 2.0), ("LENB(\"abc\")", 3.0), ("AGGREGATE(9,6,B2:B7)", 74.0),
    ("AGGREGATE(14,6,B2:B7,2)", 14.0), ("SERIESSUM(2,0,1,B2:B4)", 18 + 24 + 52.0),
]


@pytest.mark.parametrize("formula,expected", CASES, ids=[c[0] for c in CASES])
def test_more(formula, expected):
    got = show(ev(formula, ENV))
    if isinstance(expected, str):
        assert got == expected
    else:
        assert got == pytest.approx(expected, rel=1e-6, abs=1e-9), got


LAMBDA_CASES = [
    ("LET(x,5,y,x*2,x+y)", 15.0), ("LET(x,A2:A7,COUNTA(x))", 6.0), ("LET(f,LAMBDA(a,b,a*b),f(3,4))", 12.0),
    ("LAMBDA(x,x+1)", "#CALC!"), ("SUM(MAP(B2:B4,LAMBDA(v,v*v)))", 18**2 + 12**2 + 13**2 + 0.0),
    ("REDUCE(0,B2:B4,LAMBDA(a,v,a+v))", 43.0), ("INDEX(SCAN(0,B2:B4,LAMBDA(a,v,a+v)),3)", 43.0),
    ("SUM(BYROW(B2:C3,LAMBDA(r,SUM(r)*10)))", (18 + 20 + 12 + 12) * 10.0), ("INDEX(MAKEARRAY(3,3,LAMBDA(r,c,r*c)),3,3)", 9.0),
    ("LET(x,1,LET(y,x+1,x+y))", 3.0), ("_xlfn.LET(_xlpm.x,2,_xlpm.x*3)", 6.0), ("LET(x,1)", "#VALUE!"),
]


@pytest.mark.parametrize("formula,expected", LAMBDA_CASES, ids=[c[0] for c in LAMBDA_CASES])
def test_lambda_family(formula, expected):
    got = show(ev(formula, ENV))
    assert got == (pytest.approx(expected) if not isinstance(expected, str) else expected)


def test_to_file_formula_adds_prefixes():
    from gridora_engine.formula.parser import to_file_formula as f
    assert f('IFS(A1>1,"a",TRUE,"b")') == '_xlfn.IFS(A1>1,"a",TRUE,"b")'
    assert f("_xlfn.IFS(1,2)") == "_xlfn.IFS(1,2)"
    assert f("SUM(1)+SORT(A1:A3)") == "SUM(1)+_xlfn._xlws.SORT(A1:A3)"
    assert f('"IFS(" & 1') == '"IFS(" & 1'
