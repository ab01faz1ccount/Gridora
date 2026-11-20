from __future__ import annotations

import math
from typing import Any

from .. import xlerrors as E
from ..values import XlRaise, to_num
from .helpers import matrix_rows, num, numbers, opt_num
from .registry import fn


def _pmt(rate: float, nper: float, pv: float, fv: float, typ: int) -> float:
    if rate == 0:
        return -(pv + fv) / nper
    f = (1 + rate) ** nper
    return -(rate * (pv * f + fv)) / ((1 + rate * typ) * (f - 1))


@fn("PMT", 3, 5)
def f_pmt(ctx: Any, rate: Any, nper: Any, pv: Any, fv: Any = None, typ: Any = None) -> float:
    n = num(ctx, nper)
    if n == 0:
        raise XlRaise(E.NUM)
    return _pmt(num(ctx, rate), n, num(ctx, pv), opt_num(ctx, fv, 0), int(opt_num(ctx, typ, 0) != 0))


@fn("FV", 3, 5)
def f_fv(ctx: Any, rate: Any, nper: Any, pmt: Any, pv: Any = None, typ: Any = None) -> float:
    r, n, p = num(ctx, rate), num(ctx, nper), num(ctx, pmt)
    pvv, t = opt_num(ctx, pv, 0), int(opt_num(ctx, typ, 0) != 0)
    if r == 0:
        return -(pvv + p * n)
    f = (1 + r) ** n
    return -(pvv * f + p * (1 + r * t) * (f - 1) / r)


@fn("PV", 3, 5)
def f_pv(ctx: Any, rate: Any, nper: Any, pmt: Any, fv: Any = None, typ: Any = None) -> float:
    r, n, p = num(ctx, rate), num(ctx, nper), num(ctx, pmt)
    fvv, t = opt_num(ctx, fv, 0), int(opt_num(ctx, typ, 0) != 0)
    if r == 0:
        return -(fvv + p * n)
    f = (1 + r) ** n
    return -(fvv + p * (1 + r * t) * (f - 1) / r) / f


@fn("NPER", 3, 5)
def f_nper(ctx: Any, rate: Any, pmt: Any, pv: Any, fv: Any = None, typ: Any = None) -> float:
    r, p, pvv = num(ctx, rate), num(ctx, pmt), num(ctx, pv)
    fvv, t = opt_num(ctx, fv, 0), int(opt_num(ctx, typ, 0) != 0)
    if r == 0:
        if p == 0:
            raise XlRaise(E.NUM)
        return -(pvv + fvv) / p
    a = p * (1 + r * t) / r
    num_, den = a - fvv, a + pvv
    if den == 0 or num_ / den <= 0:
        raise XlRaise(E.NUM)
    return math.log(num_ / den) / math.log(1 + r)


def _ipmt_end(r: float, k: float, pv: float, pay: float) -> float:
    if r == 0:
        return 0.0
    f = (1 + r) ** (k - 1)
    balance = pv * f + pay * (f - 1) / r
    return -balance * r


@fn("IPMT", 4, 6)
def f_ipmt(ctx: Any, rate: Any, per: Any, nper: Any, pv: Any, fv: Any = None, typ: Any = None) -> float:
    r, k, n, pvv = num(ctx, rate), num(ctx, per), num(ctx, nper), num(ctx, pv)
    fvv, t = opt_num(ctx, fv, 0), int(opt_num(ctx, typ, 0) != 0)
    if k < 1 or k > n:
        raise XlRaise(E.NUM)
    pay = _pmt(r, n, pvv, fvv, t)
    if not t:
        return _ipmt_end(r, k, pvv, pay)
    if k == 1:
        return 0.0
    return _ipmt_end(r, k - 1, pvv, pay) / (1 + r)


@fn("PPMT", 4, 6)
def f_ppmt(ctx: Any, rate: Any, per: Any, nper: Any, pv: Any, fv: Any = None, typ: Any = None) -> float:
    pay = f_pmt(ctx, rate, nper, pv, fv, typ)
    return pay - f_ipmt(ctx, rate, per, nper, pv, fv, typ)


@fn("SLN", 3, 3)
def f_sln(ctx: Any, cost: Any, salvage: Any, life: Any) -> float:
    n = num(ctx, life)
    if n == 0:
        raise XlRaise(E.DIV0)
    return (num(ctx, cost) - num(ctx, salvage)) / n


@fn("NPV", 2, -1)
def f_npv(ctx: Any, rate: Any, *vals: Any) -> float:
    r = num(ctx, rate)
    if r == -1:
        raise XlRaise(E.DIV0)
    return sum(v / (1 + r) ** (i + 1) for i, v in enumerate(numbers(vals)))


def _cashflows(a: Any) -> list[float]:
    flows = [float(x) for row in matrix_rows(a) for x in row if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not any(f > 0 for f in flows) or not any(f < 0 for f in flows):
        raise XlRaise(E.NUM)
    return flows


@fn("IRR", 1, 2)
def f_irr(ctx: Any, vals: Any, guess: Any = None) -> float:
    flows = _cashflows(vals)
    r = opt_num(ctx, guess, 0.1)

    def f(x: float) -> float:
        return sum(c / (1 + x) ** i for i, c in enumerate(flows))

    def d(x: float) -> float:
        return sum(-i * c / (1 + x) ** (i + 1) for i, c in enumerate(flows))

    for _ in range(100):
        fx, dx = f(r), d(r)
        if dx == 0:
            break
        nr = r - fx / dx
        if nr <= -1:
            nr = (r - 1) / 2
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    raise XlRaise(E.NUM)


@fn("RATE", 3, 6)
def f_rate(ctx: Any, nper: Any, pmt: Any, pv: Any, fv: Any = None, typ: Any = None, guess: Any = None) -> float:
    n, p, pvv = num(ctx, nper), num(ctx, pmt), num(ctx, pv)
    fvv, t = opt_num(ctx, fv, 0), int(opt_num(ctx, typ, 0) != 0)
    r = opt_num(ctx, guess, 0.1)

    def f(x: float) -> float:
        if abs(x) < 1e-12:
            return pvv + p * n + fvv
        g = (1 + x) ** n
        return pvv * g + p * (1 + x * t) * (g - 1) / x + fvv

    for _ in range(200):
        h = 1e-7
        fx = f(r)
        d = (f(r + h) - fx) / h
        if d == 0:
            break
        nr = r - fx / d
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    raise XlRaise(E.NUM)
