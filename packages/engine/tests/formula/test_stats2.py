from __future__ import annotations

import pytest

from .envkit import DictEnv, ev, show

ENV = DictEnv({(0, 0, 0): 1., (0, 1, 0): 2., (0, 2, 0): 3., (0, 3, 0): 4., (0, 4, 0): 5.,
               (0, 0, 1): 2., (0, 1, 1): 4., (0, 2, 1): 5., (0, 3, 1): 4., (0, 4, 1): 5.})

# Values from Microsoft's function documentation unless noted.
CASES = [
    ("T.DIST(1,10,TRUE)", 0.8295534338), ("T.INV.2T(0.05,10)", 2.2281388520), ("T.INV(0.9,5)", 1.4758840488),
    ("CHISQ.DIST.RT(3,2)", 0.2231301601), ("CHISQ.INV.RT(0.05,2)", 5.9914645471), ("CHISQ.DIST(0.5,1,TRUE)", 0.5204998778),
    ("F.DIST.RT(15.2069,6,4)", 0.01), ("F.INV.RT(0.01,6,4)", 15.20686486),
    ("POISSON.DIST(2,3,FALSE)", 0.2240418077), ("POISSON.DIST(2,5,TRUE)", 0.1246520195),
    ("BINOM.DIST(3,10,0.5,FALSE)", 0.1171875), ("BINOM.DIST(6,10,0.5,TRUE)", 0.828125), ("BINOM.INV(6,0.5,0.75)", 4.0),
    ("GAMMA.DIST(10.00001131,9,2,TRUE)", 0.068094), ("BETA.DIST(2,8,10,TRUE,1,3)", 0.685470581),
    ("WEIBULL.DIST(105,20,100,TRUE)", 0.929581), ("LOGNORM.DIST(4,3.5,1.2,TRUE)", 0.0390836),
    ("HYPGEOM.DIST(1,4,8,20,FALSE)", 0.3632610939), ("NEGBINOM.DIST(10,5,0.25,FALSE)", 0.0550486604),
    ("EXPON.DIST(0.2,10,TRUE)", 0.8646647168), ("CONFIDENCE.NORM(0.05,2.5,50)", 0.6929519122),
    ("FISHER(0.75)", 0.9729550745), ("GAMMALN(4)", 1.7917594692), ("GAMMA(2.5)", 1.3293403882), ("GAUSS(2)", 0.4772498681),
    ("PERCENTRANK.INC(A1:A5,2)", 0.25), ("PERCENTRANK.INC(A1:A5,2.5)", 0.375), ("PERCENTRANK.EXC(A1:A5,2)", 0.333),
    ("TRIMMEAN(A1:A5,0.4)", 3.0), ("SKEW.P(A1:A5)", 0.0), ("SUMX2MY2(A1:A5,B1:B5)", -31.0), ("SUMXMY2(A1:A5,B1:B5)", 9.0),
    ("MULTINOMIAL(2,3,4)", 1260.0), ("COMBINA(4,3)", 20.0), ("T.TEST(A1:A5,B1:B5,2,1)", 0.0890093425),
    ("T.DIST(0,0,TRUE)", "#NUM!"), ("CHISQ.INV(1.5,2)", "#NUM!"), ("NORM.S.INV(0)", "#NUM!"),
]


@pytest.mark.parametrize("formula,expected", CASES, ids=[c[0] for c in CASES])
def test_stats2(formula, expected):
    got = show(ev(formula, ENV))
    if isinstance(expected, str):
        assert got == expected
    else:
        assert got == pytest.approx(expected, rel=1e-5, abs=1e-9), got
