from __future__ import annotations

import math
import random
from typing import Any

from .. import xlerrors as E
from ..values import Arr, RangeVal, XlRaise, check, finite, to_int
from ..xlerrors import XlError
from .helpers import integer, matrix_rows, num, numbers, opt_num, round_half_up
from .registry import fn


@fn("SUM", 1, -1)
def f_sum(ctx: Any, *args: Any) -> float:
    return finite(math.fsum(numbers(args)))


@fn("PRODUCT", 1, -1)
def f_product(ctx: Any, *args: Any) -> float:
    p, seen = 1.0, False
    for x in numbers(args):
        p *= x
        seen = True
    return finite(p) if seen else 0.0


@fn("SUMSQ", 1, -1)
def f_sumsq(ctx: Any, *args: Any) -> float:
    return finite(math.fsum(x * x for x in numbers(args)))


@fn("ABS", 1, 1)
def f_abs(ctx: Any, a: Any) -> float:
    return abs(num(ctx, a))


@fn("SIGN", 1, 1)
def f_sign(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    return float((x > 0) - (x < 0))


@fn("SQRT", 1, 1)
def f_sqrt(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    if x < 0:
        raise XlRaise(E.NUM)
    return math.sqrt(x)


@fn("SQRTPI", 1, 1)
def f_sqrtpi(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    if x < 0:
        raise XlRaise(E.NUM)
    return math.sqrt(x * math.pi)


@fn("POWER", 2, 2)
def f_power(ctx: Any, a: Any, b: Any) -> Any:
    from ..evaluator import power

    return power(num(ctx, a), num(ctx, b))


@fn("EXP", 1, 1)
def f_exp(ctx: Any, a: Any) -> float:
    return finite(math.exp(num(ctx, a)))


@fn("LN", 1, 1)
def f_ln(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    if x <= 0:
        raise XlRaise(E.NUM)
    return math.log(x)


@fn("LOG10", 1, 1)
def f_log10(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    if x <= 0:
        raise XlRaise(E.NUM)
    return math.log10(x)


@fn("LOG", 1, 2)
def f_log(ctx: Any, a: Any, b: Any = None) -> float:
    x = num(ctx, a)
    base = 10.0 if b is None else num(ctx, b)
    if x <= 0 or base <= 0 or base == 1:
        raise XlRaise(E.NUM if base != 1 else E.DIV0)
    return math.log(x) / math.log(base)


@fn("MOD", 2, 2)
def f_mod(ctx: Any, a: Any, b: Any) -> float:
    x, y = num(ctx, a), num(ctx, b)
    if y == 0:
        raise XlRaise(E.DIV0)
    return x - y * math.floor(x / y)


@fn("QUOTIENT", 2, 2)
def f_quotient(ctx: Any, a: Any, b: Any) -> float:
    x, y = num(ctx, a), num(ctx, b)
    if y == 0:
        raise XlRaise(E.DIV0)
    return float(math.trunc(x / y))


@fn("INT", 1, 1)
def f_int(ctx: Any, a: Any) -> float:
    return float(math.floor(num(ctx, a)))


@fn("TRUNC", 1, 2)
def f_trunc(ctx: Any, a: Any, d: Any = None) -> float:
    x = num(ctx, a)
    digits = int(opt_num(ctx, d, 0))
    f = 10.0 ** digits
    return math.trunc(x * f) / f


@fn("ROUND", 2, 2)
def f_round(ctx: Any, a: Any, d: Any) -> float:
    return round_half_up(num(ctx, a), integer(ctx, d))


@fn("ROUNDUP", 2, 2)
def f_roundup(ctx: Any, a: Any, d: Any) -> float:
    x, digits = num(ctx, a), integer(ctx, d)
    f = 10.0 ** digits
    r = math.ceil(abs(round_half_up(x * f, 9))) / f
    return math.copysign(r, x) if r else 0.0


@fn("ROUNDDOWN", 2, 2)
def f_rounddown(ctx: Any, a: Any, d: Any) -> float:
    x, digits = num(ctx, a), integer(ctx, d)
    f = 10.0 ** digits
    r = math.floor(abs(round_half_up(x * f, 9))) / f
    return math.copysign(r, x) if r else 0.0


@fn("MROUND", 2, 2)
def f_mround(ctx: Any, a: Any, m: Any) -> float:
    x, mult = num(ctx, a), num(ctx, m)
    if mult == 0:
        return 0.0
    if x * mult < 0:
        raise XlRaise(E.NUM)
    return round_half_up(x / mult, 0) * mult


def _ceil_floor(x: float, sig: float, up: bool, mode: int = 0) -> float:
    if sig == 0:
        return 0.0
    if x == 0:
        return 0.0
    s = abs(sig)
    if x > 0:
        return (math.ceil(x / s - 1e-12) if up else math.floor(x / s + 1e-12)) * s
    # negative numbers: mode 0 rounds toward +inf for CEILING.MATH ("up"), away from zero otherwise
    if up:
        return (math.floor(x / s + 1e-12) if mode else math.ceil(x / s - 1e-12)) * s
    return (math.ceil(x / s - 1e-12) if mode else math.floor(x / s + 1e-12)) * s


def _legacy_round(x: float, sig: float, up: bool) -> float:
    """CEILING/FLOOR as Excel documents them: ceil(x/sig)*sig, floor(x/sig)*sig."""
    if sig == 0 or x == 0:
        return 0.0
    q = x / sig
    r = math.ceil(q - 1e-12) if up else math.floor(q + 1e-12)
    return r * sig


@fn("CEILING", 1, 2)
def f_ceiling(ctx: Any, a: Any, s: Any = None) -> float:
    x = num(ctx, a)
    sig = (1.0 if x >= 0 else -1.0) if s is None else num(ctx, s)
    if x > 0 and sig < 0:
        raise XlRaise(E.NUM)
    return _legacy_round(x, sig, True)


@fn("CEILING.PRECISE", 1, 2, aliases=("ISO.CEILING",))
def f_ceiling_precise(ctx: Any, a: Any, s: Any = None) -> float:
    return _ceil_floor(num(ctx, a), 1.0 if s is None else num(ctx, s), True)


@fn("CEILING.MATH", 1, 3)
def f_ceiling_math(ctx: Any, a: Any, s: Any = None, m: Any = None) -> float:
    x = num(ctx, a)
    sig = 1.0 if s is None else num(ctx, s)
    return _ceil_floor(x, sig, True, int(opt_num(ctx, m, 0)))


@fn("FLOOR", 1, 2)
def f_floor(ctx: Any, a: Any, s: Any = None) -> float:
    x = num(ctx, a)
    sig = (1.0 if x >= 0 else -1.0) if s is None else num(ctx, s)
    if x > 0 and sig < 0:
        raise XlRaise(E.NUM)
    if sig == 0:
        raise XlRaise(E.DIV0)
    return _legacy_round(x, sig, False)


@fn("FLOOR.PRECISE", 1, 2)
def f_floor_precise(ctx: Any, a: Any, s: Any = None) -> float:
    return _ceil_floor(num(ctx, a), 1.0 if s is None else num(ctx, s), False)


@fn("FLOOR.MATH", 1, 3)
def f_floor_math(ctx: Any, a: Any, s: Any = None, m: Any = None) -> float:
    x = num(ctx, a)
    sig = 1.0 if s is None else num(ctx, s)
    return _ceil_floor(x, sig, False, int(opt_num(ctx, m, 0)))


@fn("EVEN", 1, 1)
def f_even(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    r = math.ceil(abs(x) / 2) * 2
    return math.copysign(r, x) if r else 0.0


@fn("ODD", 1, 1)
def f_odd(ctx: Any, a: Any) -> float:
    x = num(ctx, a)
    r = math.ceil(abs(x))
    r = r if r % 2 == 1 else r + 1
    return math.copysign(r, x)


@fn("PI", 0, 0)
def f_pi(ctx: Any) -> float:
    return math.pi


def _trig(name: str, f, domain=None):
    @fn(name, 1, 1)
    def _t(ctx: Any, a: Any) -> float:
        x = num(ctx, a)
        if domain and not domain(x):
            raise XlRaise(E.NUM)
        return finite(f(x))

    return _t


_trig("SIN", math.sin)
_trig("COS", math.cos)
_trig("TAN", math.tan)
_trig("ASIN", math.asin, lambda x: -1 <= x <= 1)
_trig("ACOS", math.acos, lambda x: -1 <= x <= 1)
_trig("ATAN", math.atan)
_trig("SINH", math.sinh)
_trig("COSH", math.cosh)
_trig("TANH", math.tanh)
_trig("ASINH", math.asinh)
_trig("ACOSH", math.acosh, lambda x: x >= 1)
_trig("ATANH", math.atanh, lambda x: -1 < x < 1)
_trig("DEGREES", math.degrees)
_trig("RADIANS", math.radians)
_trig("COT", lambda x: 1 / math.tan(x))
_trig("SEC", lambda x: 1 / math.cos(x))
_trig("CSC", lambda x: 1 / math.sin(x))


@fn("ATAN2", 2, 2)
def f_atan2(ctx: Any, x: Any, y: Any) -> float:
    a, b = num(ctx, x), num(ctx, y)
    if a == 0 and b == 0:
        raise XlRaise(E.DIV0)
    return math.atan2(b, a)


@fn("FACT", 1, 1)
def f_fact(ctx: Any, a: Any) -> float:
    x = math.floor(num(ctx, a))
    if x < 0 or x > 170:
        raise XlRaise(E.NUM)
    return float(math.factorial(x))


@fn("FACTDOUBLE", 1, 1)
def f_factdouble(ctx: Any, a: Any) -> float:
    n = math.floor(num(ctx, a))
    if n < -1:
        raise XlRaise(E.NUM)
    r = 1.0
    while n > 1:
        r *= n
        n -= 2
    return finite(r)


@fn("COMBIN", 2, 2)
def f_combin(ctx: Any, a: Any, b: Any) -> float:
    n, k = math.trunc(num(ctx, a)), math.trunc(num(ctx, b))
    if n < 0 or k < 0 or k > n:
        raise XlRaise(E.NUM)
    return finite(float(math.comb(n, k)))


@fn("PERMUT", 2, 2)
def f_permut(ctx: Any, a: Any, b: Any) -> float:
    n, k = math.trunc(num(ctx, a)), math.trunc(num(ctx, b))
    if n < 0 or k < 0 or k > n:
        raise XlRaise(E.NUM)
    return finite(float(math.perm(n, k)))


@fn("GCD", 1, -1)
def f_gcd(ctx: Any, *args: Any) -> float:
    vals = [math.trunc(x) for x in numbers(args)]
    if any(v < 0 for v in vals):
        raise XlRaise(E.NUM)
    return float(math.gcd(*vals))


@fn("LCM", 1, -1)
def f_lcm(ctx: Any, *args: Any) -> float:
    vals = [math.trunc(x) for x in numbers(args)]
    if any(v < 0 for v in vals):
        raise XlRaise(E.NUM)
    return finite(float(math.lcm(*vals)))


@fn("RAND", 0, 0, volatile=True)
def f_rand(ctx: Any) -> float:
    return random.random()


@fn("RANDBETWEEN", 2, 2, volatile=True)
def f_randbetween(ctx: Any, a: Any, b: Any) -> float:
    lo, hi = math.ceil(num(ctx, a)), math.floor(num(ctx, b))
    if lo > hi:
        raise XlRaise(E.NUM)
    return float(random.randint(lo, hi))


@fn("SUMPRODUCT", 1, -1, arr=True)
def f_sumproduct(ctx: Any, *args: Any) -> float:
    mats = []
    for a in args:
        if isinstance(a, XlError):
            raise XlRaise(a)
        mats.append(matrix_rows(a))
    shape = (len(mats[0]), len(mats[0][0]) if mats[0] else 0)
    for m in mats:
        if (len(m), len(m[0]) if m else 0) != shape:
            raise XlRaise(E.VALUE)
    total = 0.0
    for i in range(shape[0]):
        for j in range(shape[1]):
            p = 1.0
            for m in mats:
                x = m[i][j]
                if isinstance(x, XlError):
                    raise XlRaise(x)
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    x = 0.0 if not isinstance(x, bool) else float(x) * 0  # non-numbers count as 0
                p *= x
            total += p
    return finite(total)


_SUBTOTAL = {
    1: "AVERAGE", 2: "COUNT", 3: "COUNTA", 4: "MAX", 5: "MIN", 6: "PRODUCT", 7: "STDEV.S",
    8: "STDEV.P", 9: "SUM", 10: "VAR.S", 11: "VAR.P",
}


@fn("SUBTOTAL", 2, -1)
def f_subtotal(ctx: Any, code: Any, *refs: Any) -> Any:
    from . import REGISTRY

    n = to_int(check(ctx.scalar(code)))
    base = n - 100 if n > 100 else n
    name = _SUBTOTAL.get(base)
    if name is None:
        raise XlRaise(E.VALUE)
    skip = getattr(ctx.env, "is_subtotal_cell", None)
    filtered: list[Any] = []
    for r in refs:
        if isinstance(r, RangeVal) and skip is not None:
            rows = []
            for i in range(r.nrows):
                row = []
                for j in range(r.ncols):
                    row.append(None if skip(r.sheet, r.r0 + i, r.c0 + j) else r.at(i, j))
                rows.append(row)
            filtered.append(Arr(rows))
        else:
            filtered.append(r)
    return REGISTRY[name].fn(ctx, *filtered)


@fn("TRANSPOSE", 1, 1, arr=True)
def f_transpose(ctx: Any, a: Any) -> Arr:
    rows = matrix_rows(a)
    return Arr([list(col) for col in zip(*rows)]) if rows else Arr([[E.VALUE]])


@fn("SEQUENCE", 1, 4, arr=True)
def f_sequence(ctx: Any, r: Any, c: Any = None, start: Any = None, step: Any = None) -> Arr:
    n, m = integer(ctx, r), int(opt_num(ctx, c, 1))
    s, st = opt_num(ctx, start, 1), opt_num(ctx, step, 1)
    if n < 1 or m < 1 or n * m > 1_000_000:
        raise XlRaise(E.VALUE)
    return Arr([[s + (i * m + j) * st for j in range(m)] for i in range(n)])


def _mat(a: Any) -> list[list[float]]:
    rows = matrix_rows(a)
    out = []
    for row in rows:
        orow = []
        for x in row:
            if isinstance(x, XlError):
                raise XlRaise(x)
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                raise XlRaise(E.VALUE)
            orow.append(float(x))
        out.append(orow)
    if not out or not out[0]:
        raise XlRaise(E.VALUE)
    return out


@fn("MMULT", 2, 2, arr=True)
def f_mmult(ctx: Any, a: Any, b: Any) -> Arr:
    x, y = _mat(a), _mat(b)
    if len(x[0]) != len(y):
        raise XlRaise(E.VALUE)
    return Arr([[sum(x[i][k] * y[k][j] for k in range(len(y))) for j in range(len(y[0]))] for i in range(len(x))])


def _det(m: list[list[float]]) -> float:
    n = len(m)
    a = [row[:] for row in m]
    det = 1.0
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(a[r][i]))
        if abs(a[p][i]) < 1e-300:
            return 0.0
        if p != i:
            a[i], a[p] = a[p], a[i]
            det = -det
        det *= a[i][i]
        for r in range(i + 1, n):
            f = a[r][i] / a[i][i]
            for c in range(i, n):
                a[r][c] -= f * a[i][c]
    return det


@fn("MDETERM", 1, 1, arr=True)
def f_mdeterm(ctx: Any, a: Any) -> float:
    m = _mat(a)
    if len(m) != len(m[0]):
        raise XlRaise(E.VALUE)
    return _det(m)


@fn("MINVERSE", 1, 1, arr=True)
def f_minverse(ctx: Any, a: Any) -> Arr:
    m = _mat(a)
    n = len(m)
    if n != len(m[0]):
        raise XlRaise(E.VALUE)
    aug = [m[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(aug[r][i]))
        if abs(aug[p][i]) < 1e-12:
            raise XlRaise(E.NUM)
        aug[i], aug[p] = aug[p], aug[i]
        piv = aug[i][i]
        aug[i] = [v / piv for v in aug[i]]
        for r in range(n):
            if r != i:
                f = aug[r][i]
                aug[r] = [v - f * w for v, w in zip(aug[r], aug[i])]
    return Arr([row[n:] for row in aug])
