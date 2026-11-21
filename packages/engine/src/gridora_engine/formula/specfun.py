"""Special functions behind the probability distributions (no third-party dependencies)."""
from __future__ import annotations

import math
from collections.abc import Callable

_EPS = 1e-15
_TINY = 1e-300


def gamma_p(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x)."""
    if x <= 0:
        return 0.0
    if x < a + 1:
        term = total = 1.0 / a
        ap = a
        for _ in range(10000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    return 1.0 - _gamma_q_cf(a, x)


def _gamma_q_cf(a: float, x: float) -> float:
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = _TINY if abs(d) < _TINY else d
        c = b + an / c
        c = _TINY if abs(c) < _TINY else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gamma_q(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    return 1.0 - gamma_p(a, x) if x < a + 1 else _gamma_q_cf(a, x)


def beta_inc(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(ln_front) * _beta_cf(x, a, b) / a
    return 1.0 - math.exp(ln_front) * _beta_cf(1 - x, b, a) / b


def _beta_cf(x: float, a: float, b: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = _TINY if abs(d) < _TINY else d
    d = 1.0 / d
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = _TINY if abs(d) < _TINY else d
        c = 1.0 + aa / c
        c = _TINY if abs(c) < _TINY else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = _TINY if abs(d) < _TINY else d
        c = 1.0 + aa / c
        c = _TINY if abs(c) < _TINY else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def invert(cdf: Callable[[float], float], p: float, lo: float, hi: float, *, grow: bool = False) -> float:
    """Solve cdf(x) = p for a non-decreasing cdf by bracketing + bisection (to double precision)."""
    if grow:
        while cdf(hi) < p and hi < 1e300:
            lo, hi = hi, hi * 2 if hi > 0 else 1.0
    for _ in range(300):
        mid = (lo + hi) / 2
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-15 * max(1.0, abs(mid)):
            break
    return (lo + hi) / 2


def t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    tail = 0.5 * beta_inc(x, df / 2, 0.5)
    return 1 - tail if t > 0 else tail


def t_pdf(t: float, df: float) -> float:
    return math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi) * (1 + t * t / df) ** (-(df + 1) / 2)


def t_inv(p: float, df: float) -> float:
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_inv(1 - p, df)
    return invert(lambda x: t_cdf(x, df), p, 0.0, 10.0, grow=True)


def chi2_cdf(x: float, df: float) -> float:
    return gamma_p(df / 2, x / 2)


def chi2_pdf(x: float, df: float) -> float:
    if x < 0:
        return 0.0
    if x == 0:
        return 0.5 if df == 2 else (math.inf if df < 2 else 0.0)
    return math.exp((df / 2 - 1) * math.log(x) - x / 2 - (df / 2) * math.log(2) - math.lgamma(df / 2))


def f_cdf(x: float, d1: float, d2: float) -> float:
    if x <= 0:
        return 0.0
    return beta_inc(d1 * x / (d1 * x + d2), d1 / 2, d2 / 2)


def f_pdf(x: float, d1: float, d2: float) -> float:
    if x < 0:
        return 0.0
    if x == 0:
        return 1.0 if d1 == 2 else (math.inf if d1 < 2 else 0.0)
    ln = (math.lgamma((d1 + d2) / 2) - math.lgamma(d1 / 2) - math.lgamma(d2 / 2)
          + (d1 / 2) * math.log(d1 / d2) + (d1 / 2 - 1) * math.log(x) - ((d1 + d2) / 2) * math.log1p(d1 * x / d2))
    return math.exp(ln)


def beta_pdf(x: float, a: float, b: float) -> float:
    if x < 0 or x > 1:
        return 0.0
    if x in (0.0, 1.0):
        edge = a if x == 0 else b
        if edge < 1:
            return math.inf
        if edge > 1:
            return 0.0
    return math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + (a - 1) * math.log(x) + (b - 1) * math.log1p(-x))


def gamma_pdf(x: float, a: float, scale: float) -> float:
    if x < 0:
        return 0.0
    if x == 0:
        return (1 / scale if a == 1 else math.inf) if a <= 1 else 0.0
    return math.exp((a - 1) * math.log(x) - x / scale - a * math.log(scale) - math.lgamma(a))


def log_comb(n: float, k: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
