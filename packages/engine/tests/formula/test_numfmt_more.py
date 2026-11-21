from __future__ import annotations

import pytest

from .envkit import ev

CASES = [
    ('TEXT(1.5,"# ?/?")', "1 1/2"), ('TEXT(0.333,"?/?")', "1/3"), ('TEXT(3.14159,"# ??/??")', "3 14/99"),
    ('TEXT(2.5,"# #/#")', "2 1/2"), ('TEXT(1,"# ?/?")', "1    "), ('TEXT(1.25,"# ??/16")', "1  4/16"),
    ('TEXT(-1.5,"# ?/?")', "-1 1/2"), ('TEXT(1234567,"0,0000000")', "01,234,567"),
    ('TEXT(1234567.891,"#,##0.00")', "1,234,567.89"), ('TEXT(0.5,"#.00")', ".50"), ('TEXT(5,"000")', "005"),
    ('TEXT(1.5,"0.0?")', "1.5 "), ('TEXT(12,"??0")', " 12"), ('TEXT(-1234.5,"#,##0.00")', "-1,234.50"),
    ('TEXT(1e6,"0.00E+00")', "1.00E+06"), ('TEXT(0.05,"0.0%")', "5.0%"),
]


@pytest.mark.parametrize("formula,expected", CASES, ids=[c[0] for c in CASES])
def test_numfmt(formula, expected):
    assert ev(formula) == expected
