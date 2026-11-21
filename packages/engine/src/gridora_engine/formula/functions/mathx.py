"""Engineering, number-system and further math functions (E7)."""
from __future__ import annotations

import math
import re
from typing import Any

from .. import xlerrors as E
from ..values import Arr, XlRaise, to_bool, to_str
from .helpers import integer, matrix_rows, num, numbers, opt_num, scalar, text
from .registry import REGISTRY, fn


def _need(c: bool) -> None:
    if not c:
        raise XlRaise(E.NUM)


@fn("ERF", 1, 2, aliases=("ERF.PRECISE",))
def f_erf(ctx: Any, lo: Any, hi: Any = None) -> float:
    a = num(ctx, lo)
    return math.erf(a) if hi is None else math.erf(num(ctx, hi)) - math.erf(a)


@fn("ERFC", 1, 1, aliases=("ERFC.PRECISE",))
def f_erfc(ctx: Any, x: Any) -> float:
    return math.erfc(num(ctx, x))


@fn("ACOT", 1, 1)
def f_acot(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    return math.pi / 2 - math.atan(v)


@fn("ACOTH", 1, 1)
def f_acoth(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    _need(abs(v) > 1)
    return 0.5 * math.log((v + 1) / (v - 1))


@fn("COTH", 1, 1)
def f_coth(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    if v == 0:
        raise XlRaise(E.DIV0)
    return 1 / math.tanh(v)


@fn("SECH", 1, 1)
def f_sech(ctx: Any, x: Any) -> float:
    return 1 / math.cosh(num(ctx, x))


@fn("CSCH", 1, 1)
def f_csch(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    if v == 0:
        raise XlRaise(E.DIV0)
    return 1 / math.sinh(v)


# -- roman / bases ---------------------------------------------------------------------------------------
_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
          (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


@fn("ROMAN", 1, 2)
def f_roman(ctx: Any, n: Any, form: Any = None) -> str:
    v = math.floor(num(ctx, n))
    _need(0 <= v <= 3999)
    out = []
    for val, sym in _ROMAN:
        while v >= val:
            out.append(sym)
            v -= val
    return "".join(out)  # only the classic form (0) is implemented; simplified forms 1-4 give the same text


@fn("ARABIC", 1, 1)
def f_arabic(ctx: Any, s: Any) -> float:
    t = text(ctx, s).strip().upper()
    if t == "":
        return 0.0
    neg = t.startswith("-")
    t = t[1:] if neg else t
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    if not t or any(c not in vals for c in t):
        raise XlRaise(E.VALUE)
    total = 0
    for i, c in enumerate(t):
        v = vals[c]
        total += -v if i + 1 < len(t) and vals[t[i + 1]] > v else v
    return float(-total if neg else total)


_DIG = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@fn("BASE", 2, 3)
def f_base(ctx: Any, n: Any, radix: Any, minlen: Any = None) -> str:
    v, r = math.floor(num(ctx, n)), integer(ctx, radix)
    ml = 0 if minlen is None else integer(ctx, minlen)
    _need(0 <= v < 2 ** 53 and 2 <= r <= 36 and 0 <= ml <= 255)
    out = ""
    while v:
        v, d = divmod(v, r)
        out = _DIG[d] + out
    return (out or "0").rjust(ml, "0")


@fn("DECIMAL", 2, 2)
def f_decimal(ctx: Any, s: Any, radix: Any) -> float:
    t, r = text(ctx, s).strip().upper(), integer(ctx, radix)
    _need(2 <= r <= 36)
    if t == "":
        return 0.0
    if any(c not in _DIG[:r] for c in t):
        raise XlRaise(E.NUM)
    return float(int(t, r))


_BIT_MAX = 2 ** 48


def _bit(ctx: Any, v: Any) -> int:
    x = num(ctx, v)
    _need(x >= 0 and x == math.floor(x) and x < _BIT_MAX)
    return int(x)


@fn("BITAND", 2, 2)
def f_bitand(ctx: Any, a: Any, b: Any) -> float:
    return float(_bit(ctx, a) & _bit(ctx, b))


@fn("BITOR", 2, 2)
def f_bitor(ctx: Any, a: Any, b: Any) -> float:
    return float(_bit(ctx, a) | _bit(ctx, b))


@fn("BITXOR", 2, 2)
def f_bitxor(ctx: Any, a: Any, b: Any) -> float:
    return float(_bit(ctx, a) ^ _bit(ctx, b))


def _shift(v: int, s: int) -> float:
    _need(abs(s) <= 53)
    r = v << s if s >= 0 else v >> -s
    _need(r < _BIT_MAX)
    return float(r)


@fn("BITLSHIFT", 2, 2)
def f_bitlshift(ctx: Any, a: Any, s: Any) -> float:
    return _shift(_bit(ctx, a), integer(ctx, s))


@fn("BITRSHIFT", 2, 2)
def f_bitrshift(ctx: Any, a: Any, s: Any) -> float:
    return _shift(_bit(ctx, a), -integer(ctx, s))


# base conversion: 10-digit two's complement for negatives, like Excel
_RADIX_BITS = {2: 10, 8: 30, 16: 40}


def _parse_base(s: str, radix: int) -> int:
    s = s.strip().upper()
    if len(s) > 10:
        raise XlRaise(E.NUM)
    if any(c not in _DIG[:radix] for c in s):
        raise XlRaise(E.NUM)
    v = int(s or "0", radix)
    bits = _RADIX_BITS[radix]
    if len(s) == 10 and v >= 2 ** (bits - 1):
        v -= 2 ** bits
    return v


def _fmt_base(v: int, radix: int, places: int | None, lo: int, hi: int) -> str:
    _need(lo <= v <= hi)
    bits = _RADIX_BITS[radix]
    if v < 0:
        v += 2 ** bits
        s = _digits(v, radix)
        return s  # places ignored for negatives
    s = _digits(v, radix)
    if places is not None:
        _need(1 <= places <= 10 and len(s) <= places)
        s = s.rjust(places, "0")
    return s


def _digits(v: int, radix: int) -> str:
    out = ""
    while v:
        v, d = divmod(v, radix)
        out = _DIG[d] + out
    return out or "0"


_LIM = {2: (-512, 511), 8: (-(2 ** 29), 2 ** 29 - 1), 16: (-(2 ** 39), 2 ** 39 - 1)}
_NAMES = {2: "BIN", 8: "OCT", 16: "HEX"}


def _conv(src: int, dst: int) -> None:
    sn, dn = _NAMES[src], _NAMES[dst]

    @fn(f"{sn}2{dn}", 1, 2)
    def _f(ctx: Any, v: Any, places: Any = None) -> str:
        x = scalar(ctx, v)
        s = to_str(x) if not isinstance(x, (int, float)) or isinstance(x, bool) else str(int(x)) if float(x) == int(x) else str(x)
        n = _parse_base(s, src)
        p = None if places is None else integer(ctx, places)
        return _fmt_base(n, dst, p, *_LIM[dst])


for _a in (2, 8, 16):
    for _b in (2, 8, 16):
        if _a != _b:
            _conv(_a, _b)


@fn("BIN2DEC", 1, 1)
def f_bin2dec(ctx: Any, v: Any) -> float:
    return float(_parse_base(_as_text(ctx, v), 2))


@fn("OCT2DEC", 1, 1)
def f_oct2dec(ctx: Any, v: Any) -> float:
    return float(_parse_base(_as_text(ctx, v), 8))


@fn("HEX2DEC", 1, 1)
def f_hex2dec(ctx: Any, v: Any) -> float:
    return float(_parse_base(_as_text(ctx, v), 16))


def _as_text(ctx: Any, v: Any) -> str:
    x = scalar(ctx, v)
    if isinstance(x, bool):
        raise XlRaise(E.VALUE)
    if isinstance(x, (int, float)):
        return str(int(x)) if float(x) == int(x) else str(x)
    return to_str(x)


def _dec2(radix: int) -> None:
    @fn(f"DEC2{_NAMES[radix]}", 1, 2)
    def _f(ctx: Any, v: Any, places: Any = None) -> str:
        n = math.floor(num(ctx, v))
        p = None if places is None else integer(ctx, places)
        return _fmt_base(n, radix, p, *_LIM[radix])


for _r in (2, 8, 16):
    _dec2(_r)


@fn("DELTA", 1, 2)
def f_delta(ctx: Any, a: Any, b: Any = None) -> float:
    return 1.0 if num(ctx, a) == opt_num(ctx, b, 0.0) else 0.0


@fn("GESTEP", 1, 2)
def f_gestep(ctx: Any, a: Any, b: Any = None) -> float:
    return 1.0 if num(ctx, a) >= opt_num(ctx, b, 0.0) else 0.0


# -- CONVERT ---------------------------------------------------------------------------------------------
# unit -> (dimension, factor to the dimension's base unit); temperature is special-cased
_UNITS: dict[str, tuple[str, float]] = {
    "g": ("mass", 1.0), "lbm": ("mass", 453.59237), "ozm": ("mass", 28.349523125), "u": ("mass", 1.66053906660e-24),
    "stone": ("mass", 6350.29318), "ton": ("mass", 907184.74), "grain": ("mass", 0.06479891),
    "m": ("length", 1.0), "mi": ("length", 1609.344), "Nmi": ("length", 1852.0), "in": ("length", 0.0254),
    "ft": ("length", 0.3048), "yd": ("length", 0.9144), "ang": ("length", 1e-10), "pica": ("length", 0.0254 / 6),
    "yr": ("time", 31557600.0), "day": ("time", 86400.0), "d": ("time", 86400.0), "hr": ("time", 3600.0),
    "mn": ("time", 60.0), "min": ("time", 60.0), "sec": ("time", 1.0), "s": ("time", 1.0),
    "Pa": ("pressure", 1.0), "atm": ("pressure", 101325.0), "mmHg": ("pressure", 133.322387415), "psi": ("pressure", 6894.757293168),
    "Torr": ("pressure", 133.322368421),
    "N": ("force", 1.0), "dyn": ("force", 1e-5), "lbf": ("force", 4.4482216152605), "pond": ("force", 0.00980665),
    "J": ("energy", 1.0), "e": ("energy", 1e-7), "cal": ("energy", 4.1868), "BTU": ("energy", 1055.05585262),
    "Wh": ("energy", 3600.0), "eV": ("energy", 1.602176634e-19), "flb": ("energy", 1.3558179483314),
    "W": ("power", 1.0), "HP": ("power", 745.69987158227), "PS": ("power", 735.49875),
    "T": ("magnetism", 1.0), "ga": ("magnetism", 1e-4),
    "l": ("volume", 1.0), "L": ("volume", 1.0), "lt": ("volume", 1.0), "tsp": ("volume", 0.00492892159375),
    "tbs": ("volume", 0.01478676478125), "oz": ("volume", 0.0295735295625), "cup": ("volume", 0.2365882365),
    "pt": ("volume", 0.473176473), "qt": ("volume", 0.946352946), "gal": ("volume", 3.785411784),
    "ang3": ("volume", 1e-27),
    "m2": ("area", 1.0), "ha": ("area", 10000.0), "ar": ("area", 100.0), "acre": ("area", 4046.8564224),
    "mi2": ("area", 2589988.110336), "ft2": ("area", 0.09290304), "in2": ("area", 0.00064516), "yd2": ("area", 0.83612736),
    "m/s": ("speed", 1.0), "m/h": ("speed", 1 / 3600), "mph": ("speed", 0.44704), "kn": ("speed", 1852 / 3600),
    "admkn": ("speed", 1853.184 / 3600),
    "bit": ("info", 1.0), "byte": ("info", 8.0),
}
_PREFIX = {"Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "h": 1e2, "da": 10.0,
           "e": 1.0, "d": 0.1, "c": 0.01, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18,
           "z": 1e-21, "y": 1e-24}
_METRIC = {"g", "m", "sec", "s", "Pa", "N", "J", "W", "T", "l", "L", "lt", "u", "eV", "Wh", "cal", "e", "ga", "byte", "bit"}
_BINARY_PREFIX = {"Ki": 1024.0, "Mi": 1024.0 ** 2, "Gi": 1024.0 ** 3, "Ti": 1024.0 ** 4}
_TEMP = {"C": "C", "cel": "C", "F": "F", "fah": "F", "K": "K", "kel": "K"}


def _unit(u: str) -> tuple[str, float]:
    if u in _UNITS:
        return _UNITS[u]
    for pre, f in _BINARY_PREFIX.items():
        if u.startswith(pre) and u[len(pre):] in ("bit", "byte"):
            dim, base = _UNITS[u[len(pre):]]
            return dim, base * f
    for pre, f in sorted(_PREFIX.items(), key=lambda kv: -len(kv[0])):
        rest = u[len(pre):]
        if u.startswith(pre) and rest in _METRIC and rest in _UNITS:
            dim, base = _UNITS[rest]
            return dim, base * f
    raise XlRaise(E.NA)


@fn("CONVERT", 3, 3)
def f_convert(ctx: Any, n: Any, frm: Any, to: Any) -> float:
    v, a, b = num(ctx, n), text(ctx, frm), text(ctx, to)
    if a in _TEMP and b in _TEMP:
        ta, tb = _TEMP[a], _TEMP[b]
        k = v + 273.15 if ta == "C" else (v - 32) * 5 / 9 + 273.15 if ta == "F" else v
        return k - 273.15 if tb == "C" else (k - 273.15) * 9 / 5 + 32 if tb == "F" else k
    da, fa = _unit(a)
    db, fb = _unit(b)
    if da != db:
        raise XlRaise(E.NA)
    return v * fa / fb


@fn("MUNIT", 1, 1)
def f_munit(ctx: Any, n: Any) -> Arr:
    k = integer(ctx, n)
    if k < 1:
        raise XlRaise(E.VALUE)
    return Arr([[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)])


@fn("SERIESSUM", 4, 4, arr=True)
def f_seriessum(ctx: Any, x: Any, n: Any, m: Any, coeffs: Any) -> float:
    xv, nv, mv = (num(ctx, scalar(ctx, v)) for v in (x, n, m))
    total = 0.0
    for i, c in enumerate(v for r in matrix_rows(coeffs) for v in r):
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            raise XlRaise(E.VALUE)
        total += c * xv ** (nv + i * mv)
    return total


@fn("AGGREGATE", 3, -1, arr=True)
def f_aggregate(ctx: Any, func: Any, opt: Any, *refs: Any) -> Any:
    k, o = integer(ctx, scalar(ctx, func)), integer(ctx, scalar(ctx, opt))
    _need(1 <= k <= 19 and 0 <= o <= 7)
    names = {1: "AVERAGE", 2: "COUNT", 3: "COUNTA", 4: "MAX", 5: "MIN", 6: "PRODUCT", 7: "STDEV.S", 8: "STDEV.P",
             9: "SUM", 10: "VAR.S", 11: "VAR.P", 12: "MEDIAN", 13: "MODE.SNGL", 14: "LARGE", 15: "SMALL",
             16: "PERCENTILE.INC", 17: "QUARTILE.INC", 18: "PERCENTILE.EXC", 19: "QUARTILE.EXC"}
    ignore_err = o in (2, 3, 6, 7)

    def clean(a: Any) -> Any:
        rows = matrix_rows(a)
        if ignore_err:
            rows = [[v for v in r if not isinstance(v, E.XlError)] for r in rows]
            rows = [r for r in rows if r] or [[None]]
        return Arr(rows)

    if k >= 14:
        if len(refs) != 2:
            raise XlRaise(E.VALUE)
        return REGISTRY[names[k]].fn(ctx, clean(refs[0]), refs[1])
    return REGISTRY[names[k]].fn(ctx, *[clean(r) for r in refs])


@fn("HYPERLINK", 1, 2)
def f_hyperlink(ctx: Any, url: Any, name: Any = None) -> Any:
    if name is None:
        return text(ctx, url)
    return scalar(ctx, name)


_ = (numbers, re, to_bool)
