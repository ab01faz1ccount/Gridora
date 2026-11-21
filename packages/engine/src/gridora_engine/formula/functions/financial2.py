"""Further financial functions: depreciation, rate conversion, irregular cash flows, cumulative loan sums."""
from __future__ import annotations

import math
from typing import Any

from .. import xlerrors as E
from ..values import XlRaise, to_bool
from .helpers import integer, matrix_rows, num, opt_num, scalar
from .registry import fn


def _need(c: bool) -> None:
    if not c:
        raise XlRaise(E.NUM)


@fn("RRI", 3, 3)
def f_rri(ctx: Any, n: Any, pv: Any, fv: Any) -> float:
    nn, p, f = num(ctx, n), num(ctx, pv), num(ctx, fv)
    _need(nn > 0 and p != 0)
    r = f / p
    _need(r >= 0)
    return r ** (1 / nn) - 1


@fn("EFFECT", 2, 2)
def f_effect(ctx: Any, nom: Any, n: Any) -> float:
    r, k = num(ctx, nom), math.floor(num(ctx, n))
    _need(r > 0 and k >= 1)
    return (1 + r / k) ** k - 1


@fn("NOMINAL", 2, 2)
def f_nominal(ctx: Any, eff: Any, n: Any) -> float:
    r, k = num(ctx, eff), math.floor(num(ctx, n))
    _need(r > 0 and k >= 1)
    return k * ((1 + r) ** (1 / k) - 1)


@fn("SYD", 4, 4)
def f_syd(ctx: Any, cost: Any, salv: Any, life: Any, per: Any) -> float:
    c, s, lf, p = num(ctx, cost), num(ctx, salv), num(ctx, life), num(ctx, per)
    _need(lf > 0 and 1 <= p <= lf and s >= 0)
    return (c - s) * (lf - p + 1) * 2 / (lf * (lf + 1))


@fn("DB", 4, 5)
def f_db(ctx: Any, cost: Any, salv: Any, life: Any, period: Any, month: Any = None) -> float:
    c, s, lf, p = num(ctx, cost), num(ctx, salv), num(ctx, life), num(ctx, period)
    m = math.floor(opt_num(ctx, month, 12.0))
    _need(c >= 0 and s >= 0 and lf > 0 and p > 0 and 1 <= m <= 12 and p <= lf + (1 if m < 12 else 0))
    if c == 0:
        return 0.0
    rate = round(1 - (s / c) ** (1 / lf), 3)
    total = 0.0
    dep = 0.0
    for i in range(1, math.floor(p) + 1):
        if i == 1:
            dep = c * rate * m / 12
        elif i == lf + 1:
            dep = (c - total) * rate * (12 - m) / 12
        else:
            dep = (c - total) * rate
        total += dep
    return dep


def _ddb(cost: float, salv: float, life: float, period: int, factor: float) -> float:
    total = 0.0
    dep = 0.0
    for _ in range(period):
        dep = min((cost - total) * factor / life, max(cost - salv - total, 0.0))
        total += dep
    return dep


@fn("DDB", 4, 5)
def f_ddb(ctx: Any, cost: Any, salv: Any, life: Any, period: Any, factor: Any = None) -> float:
    c, s, lf, p = num(ctx, cost), num(ctx, salv), num(ctx, life), num(ctx, period)
    f = opt_num(ctx, factor, 2.0)
    _need(c >= 0 and s >= 0 and lf > 0 and p > 0 and p <= lf and f > 0)
    if p != math.floor(p):
        raise XlRaise(E.NUM)
    return _ddb(c, s, lf, int(p), f)


@fn("VDB", 5, 7)
def f_vdb(ctx: Any, cost: Any, salv: Any, life: Any, start: Any, end: Any, factor: Any = None, no_switch: Any = None) -> float:
    c, s, lf, a, b = (num(ctx, v) for v in (cost, salv, life, start, end))
    f = opt_num(ctx, factor, 2.0)
    ns = False if no_switch is None else to_bool(scalar(ctx, no_switch))
    _need(c >= 0 and s >= 0 and lf > 0 and 0 <= a <= b <= lf and f > 0)
    book = c
    total = 0.0
    for i in range(math.ceil(b)):
        ddb = min(book * f / lf, max(book - s, 0.0))
        dep = ddb
        if not ns:
            sl = max(book - s, 0.0) / (lf - i) if lf - i > 0 else 0.0
            dep = max(ddb, sl)
            dep = min(dep, max(book - s, 0.0))
        lo, hi = max(a, i), min(b, i + 1)
        if hi > lo:
            total += dep * (hi - lo)
        book -= dep
    return total


@fn("MIRR", 3, 3, arr=True)
def f_mirr(ctx: Any, vals: Any, fin: Any, rein: Any) -> float:
    flows = [float(x) for r in matrix_rows(vals) for x in r if isinstance(x, (int, float)) and not isinstance(x, bool)]
    fr, rr = num(ctx, scalar(ctx, fin)), num(ctx, scalar(ctx, rein))
    n = len(flows)
    pos = [(i, v) for i, v in enumerate(flows) if v > 0]
    neg = [(i, v) for i, v in enumerate(flows) if v < 0]
    if not pos or not neg or n < 2:
        raise XlRaise(E.DIV0)
    fv_pos = sum(v * (1 + rr) ** (n - 1 - i) for i, v in pos)
    pv_neg = sum(v / (1 + fr) ** i for i, v in neg)
    return (fv_pos / -pv_neg) ** (1 / (n - 1)) - 1


def _dated(vals: Any, dates: Any) -> tuple[list[float], list[float]]:
    v = [x for r in matrix_rows(vals) for x in r]
    d = [x for r in matrix_rows(dates) for x in r]
    if len(v) != len(d):
        raise XlRaise(E.NUM)
    for x in v + d:
        if isinstance(x, E.XlError):
            raise XlRaise(x)
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise XlRaise(E.VALUE)
    ds = [math.floor(x) for x in d]
    _need(all(x >= ds[0] for x in ds))
    return [float(x) for x in v], [float(x) for x in ds]


@fn("XNPV", 3, 3, arr=True)
def f_xnpv(ctx: Any, rate: Any, vals: Any, dates: Any) -> float:
    r = num(ctx, scalar(ctx, rate))
    _need(r > -1)
    v, d = _dated(vals, dates)
    return sum(x / (1 + r) ** ((di - d[0]) / 365) for x, di in zip(v, d, strict=True))


@fn("XIRR", 2, 3, arr=True)
def f_xirr(ctx: Any, vals: Any, dates: Any, guess: Any = None) -> float:
    v, d = _dated(vals, dates)
    if not any(x > 0 for x in v) or not any(x < 0 for x in v):
        raise XlRaise(E.NUM)
    r = 0.1 if guess is None else num(ctx, scalar(ctx, guess))
    _need(r > -1)

    def f(x: float) -> float:
        return sum(a / (1 + x) ** ((di - d[0]) / 365) for a, di in zip(v, d, strict=True))

    for _ in range(200):
        h = 1e-7
        fx = f(r)
        dx = (f(r + h) - fx) / h
        if dx == 0:
            break
        nr = r - fx / dx
        if nr <= -1:
            nr = (r - 1) / 2
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    raise XlRaise(E.NUM)


def _cum(ctx: Any, rate: Any, nper: Any, pv: Any, start: Any, end: Any, typ: Any, which: str) -> float:
    r, n, p = num(ctx, rate), num(ctx, nper), num(ctx, pv)
    s, e, t = math.floor(num(ctx, start)), math.floor(num(ctx, end)), integer(ctx, typ)
    _need(r > 0 and n > 0 and p > 0 and 1 <= s <= e <= n and t in (0, 1))
    pmt = p * r / (1 - (1 + r) ** -n)
    if t == 1:
        pmt /= 1 + r
    bal = p
    interest = principal = 0.0
    for k in range(1, e + 1):
        i = 0.0 if (t == 1 and k == 1) else bal * r
        pr = pmt - i
        bal -= pr
        if k >= s:
            interest += i
            principal += pr
    return 0.0 - (interest if which == "i" else principal)


@fn("CUMIPMT", 6, 6)
def f_cumipmt(ctx: Any, rate: Any, nper: Any, pv: Any, start: Any, end: Any, typ: Any) -> float:
    return _cum(ctx, rate, nper, pv, start, end, typ, "i")


@fn("CUMPRINC", 6, 6)
def f_cumprinc(ctx: Any, rate: Any, nper: Any, pv: Any, start: Any, end: Any, typ: Any) -> float:
    return _cum(ctx, rate, nper, pv, start, end, typ, "p")
