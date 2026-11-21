"""Probability distributions, tests and further statistics (E7)."""
from __future__ import annotations

import math
import statistics
from typing import Any

from .. import specfun as S
from .. import xlerrors as E
from ..values import Arr, XlRaise, to_bool
from ..xlerrors import XlError
from .helpers import boolean, integer, matrix_rows, num, numbers, opt_num, scalar
from .registry import fn
from .stats import _mat_numbers, _pairs

_N = statistics.NormalDist()


def _cum(ctx: Any, v: Any) -> bool:
    return to_bool(scalar(ctx, v))


def _need(cond: bool) -> None:
    if not cond:
        raise XlRaise(E.NUM)


def _prob(p: float) -> None:
    _need(0 <= p <= 1)


# -- t -------------------------------------------------------------------------------------------------
@fn("T.DIST", 3, 3)
def f_t_dist(ctx: Any, x: Any, df: Any, cum: Any) -> float:
    d = num(ctx, df)
    _need(d >= 1)
    d = math.floor(d)
    return S.t_cdf(num(ctx, x), d) if _cum(ctx, cum) else S.t_pdf(num(ctx, x), d)


@fn("T.DIST.RT", 2, 2)
def f_t_dist_rt(ctx: Any, x: Any, df: Any) -> float:
    d = num(ctx, df)
    _need(d >= 1)
    return 1 - S.t_cdf(num(ctx, x), math.floor(d))


@fn("T.DIST.2T", 2, 2)
def f_t_dist_2t(ctx: Any, x: Any, df: Any) -> float:
    d, t = num(ctx, df), num(ctx, x)
    _need(d >= 1 and t >= 0)
    return 2 * (1 - S.t_cdf(t, math.floor(d)))


@fn("TDIST", 3, 3)
def f_tdist(ctx: Any, x: Any, df: Any, tails: Any) -> float:
    d, t, k = num(ctx, df), num(ctx, x), integer(ctx, tails)
    _need(d >= 1 and t >= 0 and k in (1, 2))
    return k * (1 - S.t_cdf(t, math.floor(d)))


@fn("T.INV", 2, 2)
def f_t_inv(ctx: Any, p: Any, df: Any) -> float:
    q, d = num(ctx, p), num(ctx, df)
    _need(0 < q < 1 and d >= 1)
    return S.t_inv(q, math.floor(d))


@fn("T.INV.2T", 2, 2, aliases=("TINV",))
def f_t_inv_2t(ctx: Any, p: Any, df: Any) -> float:
    q, d = num(ctx, p), num(ctx, df)
    _need(0 < q <= 1 and d >= 1)
    return S.t_inv(1 - q / 2, math.floor(d))


# -- chi-square, F -------------------------------------------------------------------------------------
@fn("CHISQ.DIST", 3, 3)
def f_chisq_dist(ctx: Any, x: Any, df: Any, cum: Any) -> float:
    v, d = num(ctx, x), num(ctx, df)
    _need(v >= 0 and d >= 1)
    d = math.floor(d)
    return S.chi2_cdf(v, d) if _cum(ctx, cum) else S.chi2_pdf(v, d)


@fn("CHISQ.DIST.RT", 2, 2, aliases=("CHIDIST",))
def f_chisq_rt(ctx: Any, x: Any, df: Any) -> float:
    v, d = num(ctx, x), num(ctx, df)
    _need(v >= 0 and d >= 1)
    return 1 - S.chi2_cdf(v, math.floor(d))


@fn("CHISQ.INV", 2, 2)
def f_chisq_inv(ctx: Any, p: Any, df: Any) -> float:
    q, d = num(ctx, p), num(ctx, df)
    _need(0 <= q < 1 and d >= 1)
    d = math.floor(d)
    return S.invert(lambda x: S.chi2_cdf(x, d), q, 0.0, max(10.0, 2.0 * d), grow=True)


@fn("CHISQ.INV.RT", 2, 2, aliases=("CHIINV",))
def f_chisq_inv_rt(ctx: Any, p: Any, df: Any) -> float:
    q, d = num(ctx, p), num(ctx, df)
    _need(0 < q <= 1 and d >= 1)
    d = math.floor(d)
    return S.invert(lambda x: S.chi2_cdf(x, d), 1 - q, 0.0, max(10.0, 2.0 * d), grow=True)


@fn("F.DIST", 4, 4)
def f_f_dist(ctx: Any, x: Any, d1: Any, d2: Any, cum: Any) -> float:
    v, a, b = num(ctx, x), math.floor(num(ctx, d1)), math.floor(num(ctx, d2))
    _need(v >= 0 and a >= 1 and b >= 1)
    return S.f_cdf(v, a, b) if _cum(ctx, cum) else S.f_pdf(v, a, b)


@fn("F.DIST.RT", 3, 3, aliases=("FDIST",))
def f_f_dist_rt(ctx: Any, x: Any, d1: Any, d2: Any) -> float:
    v, a, b = num(ctx, x), math.floor(num(ctx, d1)), math.floor(num(ctx, d2))
    _need(v >= 0 and a >= 1 and b >= 1)
    return 1 - S.f_cdf(v, a, b)


def _f_inv(p: float, a: float, b: float) -> float:
    return S.invert(lambda x: S.f_cdf(x, a, b), p, 0.0, 10.0, grow=True)


@fn("F.INV", 3, 3)
def f_f_inv(ctx: Any, p: Any, d1: Any, d2: Any) -> float:
    q, a, b = num(ctx, p), math.floor(num(ctx, d1)), math.floor(num(ctx, d2))
    _need(0 < q < 1 and a >= 1 and b >= 1)
    return _f_inv(q, a, b)


@fn("F.INV.RT", 3, 3, aliases=("FINV",))
def f_f_inv_rt(ctx: Any, p: Any, d1: Any, d2: Any) -> float:
    q, a, b = num(ctx, p), math.floor(num(ctx, d1)), math.floor(num(ctx, d2))
    _need(0 < q < 1 and a >= 1 and b >= 1)
    return _f_inv(1 - q, a, b)


# -- gamma, beta ---------------------------------------------------------------------------------------
@fn("GAMMA.DIST", 4, 4, aliases=("GAMMADIST",))
def f_gamma_dist(ctx: Any, x: Any, a: Any, b: Any, cum: Any) -> float:
    v, al, be = num(ctx, x), num(ctx, a), num(ctx, b)
    _need(v >= 0 and al > 0 and be > 0)
    return S.gamma_p(al, v / be) if _cum(ctx, cum) else S.gamma_pdf(v, al, be)


@fn("GAMMA.INV", 3, 3, aliases=("GAMMAINV",))
def f_gamma_inv(ctx: Any, p: Any, a: Any, b: Any) -> float:
    q, al, be = num(ctx, p), num(ctx, a), num(ctx, b)
    _need(0 <= q < 1 and al > 0 and be > 0)
    return S.invert(lambda x: S.gamma_p(al, x / be), q, 0.0, max(10.0, al * be * 2), grow=True)


@fn("GAMMALN", 1, 1, aliases=("GAMMALN.PRECISE",))
def f_gammaln(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    _need(v > 0)
    return math.lgamma(v)


@fn("GAMMA", 1, 1)
def f_gamma(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    if v == math.floor(v) and v <= 0:
        raise XlRaise(E.NUM)
    try:
        return math.gamma(v)
    except OverflowError:
        raise XlRaise(E.NUM) from None


@fn("GAUSS", 1, 1)
def f_gauss(ctx: Any, z: Any) -> float:
    return _N.cdf(num(ctx, z)) - 0.5


@fn("PHI", 1, 1)
def f_phi(ctx: Any, z: Any) -> float:
    return _N.pdf(num(ctx, z))


def _beta_bounds(ctx: Any, lo: Any, hi: Any) -> tuple[float, float]:
    a = opt_num(ctx, lo, 0.0)
    b = opt_num(ctx, hi, 1.0)
    _need(a < b)
    return a, b


@fn("BETA.DIST", 4, 6)
def f_beta_dist(ctx: Any, x: Any, a: Any, b: Any, cum: Any, lo: Any = None, hi: Any = None) -> float:
    v, al, be = num(ctx, x), num(ctx, a), num(ctx, b)
    A, B = _beta_bounds(ctx, lo, hi)
    _need(al > 0 and be > 0 and A <= v <= B)
    z = (v - A) / (B - A)
    return S.beta_inc(z, al, be) if _cum(ctx, cum) else S.beta_pdf(z, al, be) / (B - A)


@fn("BETADIST", 3, 5)
def f_betadist(ctx: Any, x: Any, a: Any, b: Any, lo: Any = None, hi: Any = None) -> float:
    v, al, be = num(ctx, x), num(ctx, a), num(ctx, b)
    A, B = _beta_bounds(ctx, lo, hi)
    _need(al > 0 and be > 0 and A <= v <= B)
    return S.beta_inc((v - A) / (B - A), al, be)


@fn("BETA.INV", 3, 5, aliases=("BETAINV",))
def f_beta_inv(ctx: Any, p: Any, a: Any, b: Any, lo: Any = None, hi: Any = None) -> float:
    q, al, be = num(ctx, p), num(ctx, a), num(ctx, b)
    A, B = _beta_bounds(ctx, lo, hi)
    _need(0 < q <= 1 and al > 0 and be > 0)
    return A + (B - A) * S.invert(lambda x: S.beta_inc(x, al, be), q, 0.0, 1.0)


# -- discrete ------------------------------------------------------------------------------------------
def _binom_pmf(k: int, n: int, p: float) -> float:
    if p in (0.0, 1.0):
        return 1.0 if (k == 0) == (p == 0.0) or (p == 1.0 and k == n) else 0.0
    return math.exp(S.log_comb(n, k) + k * math.log(p) + (n - k) * math.log1p(-p))


@fn("BINOM.DIST", 4, 4, aliases=("BINOMDIST",))
def f_binom_dist(ctx: Any, k: Any, n: Any, p: Any, cum: Any) -> float:
    kk, nn, pp = math.floor(num(ctx, k)), math.floor(num(ctx, n)), num(ctx, p)
    _need(0 <= kk <= nn and 0 <= pp <= 1)
    if _cum(ctx, cum):
        return min(1.0, math.fsum(_binom_pmf(i, nn, pp) for i in range(kk + 1)))
    return _binom_pmf(kk, nn, pp)


@fn("BINOM.INV", 3, 3, aliases=("CRITBINOM",))
def f_binom_inv(ctx: Any, n: Any, p: Any, a: Any) -> float:
    nn, pp, al = math.floor(num(ctx, n)), num(ctx, p), num(ctx, a)
    _need(nn >= 0 and 0 <= pp <= 1 and 0 <= al <= 1)
    acc = 0.0
    for i in range(nn + 1):
        acc += _binom_pmf(i, nn, pp)
        if acc >= al - 1e-15:
            return float(i)
    return float(nn)


@fn("NEGBINOM.DIST", 4, 4, aliases=("NEGBINOMDIST",))
def f_negbinom(ctx: Any, f: Any, s: Any, p: Any, cum: Any = None) -> float:
    ff, ss, pp = math.floor(num(ctx, f)), math.floor(num(ctx, s)), num(ctx, p)
    _need(ff >= 0 and ss >= 1 and 0 < pp <= 1)

    def pmf(i: int) -> float:
        return math.exp(S.log_comb(i + ss - 1, ss - 1) + ss * math.log(pp) + (i * math.log1p(-pp) if pp < 1 else 0.0)) if pp < 1 or i == 0 else 0.0

    if cum is not None and _cum(ctx, cum):
        return min(1.0, math.fsum(pmf(i) for i in range(ff + 1)))
    return pmf(ff)


@fn("POISSON.DIST", 3, 3, aliases=("POISSON",))
def f_poisson(ctx: Any, x: Any, mean: Any, cum: Any) -> float:
    k, m = math.floor(num(ctx, x)), num(ctx, mean)
    _need(k >= 0 and m >= 0)
    if m == 0:
        return 1.0 if (k == 0 or _cum(ctx, cum)) else 0.0
    if _cum(ctx, cum):
        return S.gamma_q(k + 1, m)
    return math.exp(-m + k * math.log(m) - math.lgamma(k + 1))


@fn("HYPGEOM.DIST", 5, 5, aliases=("HYPGEOMDIST",))
def f_hypgeom(ctx: Any, s: Any, n: Any, ps: Any, pn: Any, cum: Any = None) -> float:
    k, n_, K, N = (math.floor(num(ctx, v)) for v in (s, n, ps, pn))
    _need(0 <= n_ <= N and 0 <= K <= N and max(0, n_ - N + K) <= k <= min(n_, K))

    def pmf(i: int) -> float:
        return math.exp(S.log_comb(K, i) + S.log_comb(N - K, n_ - i) - S.log_comb(N, n_))

    if cum is not None and _cum(ctx, cum):
        return min(1.0, math.fsum(pmf(i) for i in range(max(0, n_ - N + K), k + 1)))
    return pmf(k)


@fn("EXPON.DIST", 3, 3, aliases=("EXPONDIST",))
def f_expon(ctx: Any, x: Any, lam: Any, cum: Any) -> float:
    v, la = num(ctx, x), num(ctx, lam)
    _need(v >= 0 and la > 0)
    return 1 - math.exp(-la * v) if _cum(ctx, cum) else la * math.exp(-la * v)


@fn("WEIBULL.DIST", 4, 4, aliases=("WEIBULL",))
def f_weibull(ctx: Any, x: Any, a: Any, b: Any, cum: Any) -> float:
    v, al, be = num(ctx, x), num(ctx, a), num(ctx, b)
    _need(v >= 0 and al > 0 and be > 0)
    if _cum(ctx, cum):
        return 1 - math.exp(-((v / be) ** al))
    return al / be ** al * v ** (al - 1) * math.exp(-((v / be) ** al))


@fn("LOGNORM.DIST", 4, 4)
def f_lognorm_dist(ctx: Any, x: Any, mu: Any, sd: Any, cum: Any) -> float:
    v, m, s = num(ctx, x), num(ctx, mu), num(ctx, sd)
    _need(v > 0 and s > 0)
    if _cum(ctx, cum):
        return _N.cdf((math.log(v) - m) / s)
    return math.exp(-((math.log(v) - m) ** 2) / (2 * s * s)) / (v * s * math.sqrt(2 * math.pi))


@fn("LOGNORMDIST", 3, 3)
def f_lognormdist(ctx: Any, x: Any, mu: Any, sd: Any) -> float:
    v, m, s = num(ctx, x), num(ctx, mu), num(ctx, sd)
    _need(v > 0 and s > 0)
    return _N.cdf((math.log(v) - m) / s)


@fn("LOGNORM.INV", 3, 3, aliases=("LOGINV",))
def f_lognorm_inv(ctx: Any, p: Any, mu: Any, sd: Any) -> float:
    q, m, s = num(ctx, p), num(ctx, mu), num(ctx, sd)
    _need(0 < q < 1 and s > 0)
    return math.exp(m + s * _N.inv_cdf(q))


@fn("CONFIDENCE.NORM", 3, 3, aliases=("CONFIDENCE",))
def f_confidence_norm(ctx: Any, alpha: Any, sd: Any, size: Any) -> float:
    a, s, n = num(ctx, alpha), num(ctx, sd), math.floor(num(ctx, size))
    _need(0 < a < 1 and s > 0 and n >= 1)
    return _N.inv_cdf(1 - a / 2) * s / math.sqrt(n)


@fn("CONFIDENCE.T", 3, 3)
def f_confidence_t(ctx: Any, alpha: Any, sd: Any, size: Any) -> float:
    a, s, n = num(ctx, alpha), num(ctx, sd), math.floor(num(ctx, size))
    _need(0 < a < 1 and s > 0 and n >= 1)
    if n == 1:
        raise XlRaise(E.DIV0)
    return S.t_inv(1 - a / 2, n - 1) * s / math.sqrt(n)


@fn("FISHER", 1, 1)
def f_fisher(ctx: Any, x: Any) -> float:
    v = num(ctx, x)
    _need(-1 < v < 1)
    return math.atanh(v)


@fn("FISHERINV", 1, 1)
def f_fisherinv(ctx: Any, y: Any) -> float:
    return math.tanh(num(ctx, y))


# -- descriptive extras --------------------------------------------------------------------------------
def _flat_nums(a: Any) -> list[float]:
    return _mat_numbers(a)


@fn("PERCENTRANK.INC", 2, 3, aliases=("PERCENTRANK",), arr=True)
def f_percentrank_inc(ctx: Any, arr: Any, x: Any, sig: Any = None) -> float:
    return _percentrank(ctx, arr, x, sig, exc=False)


@fn("PERCENTRANK.EXC", 2, 3, arr=True)
def f_percentrank_exc(ctx: Any, arr: Any, x: Any, sig: Any = None) -> float:
    return _percentrank(ctx, arr, x, sig, exc=True)


def _percentrank(ctx: Any, arr: Any, x: Any, sig: Any, *, exc: bool) -> float:
    v = sorted(_flat_nums(arr))
    xv = num(ctx, scalar(ctx, x) if not isinstance(x, (Arr,)) else x)
    digits = 3 if sig is None else integer(ctx, sig)
    _need(digits >= 1)
    if not v:
        raise XlRaise(E.NA)
    n = len(v)
    if xv < v[0] or xv > v[-1]:
        raise XlRaise(E.NA)
    i = 0
    while i < n - 1 and v[i + 1] <= xv:
        i += 1
    rank: float
    if v[i] == xv:
        rank = float(i)
    else:
        rank = i + (xv - v[i]) / (v[i + 1] - v[i])
    r = (rank + 1) / (n + 1) if exc else (rank / (n - 1) if n > 1 else 1.0)
    f = 10 ** digits
    return math.floor(r * f + 1e-9) / f


@fn("SKEW.P", 1, -1)
def f_skew_p(ctx: Any, *args: Any) -> float:
    v = list(numbers(args))
    n = len(v)
    if n < 1:
        raise XlRaise(E.DIV0)
    m = math.fsum(v) / n
    s = math.sqrt(math.fsum((x - m) ** 2 for x in v) / n)
    if s == 0:
        raise XlRaise(E.DIV0)
    return math.fsum(((x - m) / s) ** 3 for x in v) / n


def _va(args: tuple) -> list[float]:
    return list(numbers(args, count_text_in_refs=True))


@fn("VARA", 1, -1)
def f_vara(ctx: Any, *args: Any) -> float:
    v = _va(args)
    if len(v) < 2:
        raise XlRaise(E.DIV0)
    return statistics.variance(v)


@fn("VARPA", 1, -1)
def f_varpa(ctx: Any, *args: Any) -> float:
    v = _va(args)
    if not v:
        raise XlRaise(E.DIV0)
    return statistics.pvariance(v)


@fn("STDEVA", 1, -1)
def f_stdeva(ctx: Any, *args: Any) -> float:
    return math.sqrt(f_vara(ctx, *args))


@fn("STDEVPA", 1, -1)
def f_stdevpa(ctx: Any, *args: Any) -> float:
    return math.sqrt(f_varpa(ctx, *args))


@fn("TRIMMEAN", 2, 2, arr=True)
def f_trimmean(ctx: Any, arr: Any, pct: Any) -> float:
    v = sorted(_flat_nums(arr))
    p = num(ctx, pct)
    _need(0 <= p < 1 and bool(v))
    k = math.floor(len(v) * p / 2)
    kept = v[k: len(v) - k]
    return math.fsum(kept) / len(kept)


@fn("MODE.MULT", 1, -1, arr=True)
def f_mode_mult(ctx: Any, *args: Any) -> Arr:
    v = list(numbers(args))
    counts: dict[float, int] = {}
    for x in v:
        counts[x] = counts.get(x, 0) + 1
    top = max(counts.values(), default=0)
    if top < 2:
        raise XlRaise(E.NA)
    return Arr([[x] for x in dict.fromkeys(v) if counts[x] == top])


@fn("STEYX", 2, 2, arr=True)
def f_steyx(ctx: Any, ys: Any, xs: Any) -> float:
    y, x = _pairs(ys, xs)
    n = len(y)
    if n < 3:
        raise XlRaise(E.DIV0)
    mx, my = math.fsum(x) / n, math.fsum(y) / n
    sxx = math.fsum((a - mx) ** 2 for a in x)
    if sxx == 0:
        raise XlRaise(E.DIV0)
    sxy = math.fsum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    syy = math.fsum((b - my) ** 2 for b in y)
    return math.sqrt(max(0.0, (syy - sxy * sxy / sxx) / (n - 2)))


def _two(a: Any, b: Any) -> tuple[list[float], list[float]]:
    ra, rb = matrix_rows(a), matrix_rows(b)
    fa = [v for r in ra for v in r]
    fb = [v for r in rb for v in r]
    if len(fa) != len(fb):
        raise XlRaise(E.NA)
    xs, ys = [], []
    for u, w in zip(fa, fb, strict=True):
        for t in (u, w):
            if isinstance(t, XlError):
                raise XlRaise(t)
        if all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in (u, w)):
            xs.append(float(u))
            ys.append(float(w))
    return xs, ys


@fn("SUMX2MY2", 2, 2, arr=True)
def f_sumx2my2(ctx: Any, a: Any, b: Any) -> float:
    x, y = _two(a, b)
    return math.fsum(p * p - q * q for p, q in zip(x, y, strict=True))


@fn("SUMX2PY2", 2, 2, arr=True)
def f_sumx2py2(ctx: Any, a: Any, b: Any) -> float:
    x, y = _two(a, b)
    return math.fsum(p * p + q * q for p, q in zip(x, y, strict=True))


@fn("SUMXMY2", 2, 2, arr=True)
def f_sumxmy2(ctx: Any, a: Any, b: Any) -> float:
    x, y = _two(a, b)
    return math.fsum((p - q) ** 2 for p, q in zip(x, y, strict=True))


@fn("PROB", 3, 4, arr=True)
def f_prob(ctx: Any, xs: Any, ps: Any, lo: Any, hi: Any = None) -> float:
    x = [v for r in matrix_rows(xs) for v in r]
    p = [v for r in matrix_rows(ps) for v in r]
    if len(x) != len(p):
        raise XlRaise(E.NA)
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in x + p):
        raise XlRaise(E.VALUE)
    _need(all(0 <= v <= 1 for v in p) and abs(math.fsum(p) - 1) < 1e-9)
    a = num(ctx, scalar(ctx, lo))
    b = a if hi is None else num(ctx, scalar(ctx, hi))
    return math.fsum(pi for xi, pi in zip(x, p, strict=True) if a <= xi <= b)


@fn("Z.TEST", 2, 3, aliases=("ZTEST",), arr=True)
def f_z_test(ctx: Any, arr: Any, x: Any, sigma: Any = None) -> float:
    v = _flat_nums(arr)
    n = len(v)
    if n == 0:
        raise XlRaise(E.NA)
    m = math.fsum(v) / n
    if sigma is None:
        if n < 2:
            raise XlRaise(E.DIV0)
        sd = statistics.stdev(v)
    else:
        sd = num(ctx, scalar(ctx, sigma))
        _need(sd > 0)
    return 1 - _N.cdf((m - num(ctx, scalar(ctx, x))) / (sd / math.sqrt(n)))


@fn("T.TEST", 4, 4, aliases=("TTEST",), arr=True)
def f_t_test(ctx: Any, a: Any, b: Any, tails: Any, kind: Any) -> float:
    k, tl = integer(ctx, scalar(ctx, kind)), integer(ctx, scalar(ctx, tails))
    _need(tl in (1, 2) and k in (1, 2, 3))
    if k == 1:
        x, y = _two(a, b)
        n = len(x)
        if n < 2:
            raise XlRaise(E.DIV0)
        d = [p - q for p, q in zip(x, y, strict=True)]
        sd = statistics.stdev(d)
        if sd == 0:
            raise XlRaise(E.DIV0)
        t, df = math.fsum(d) / n / (sd / math.sqrt(n)), float(n - 1)
    else:
        x, y = _flat_nums(a), _flat_nums(b)
        n1, n2 = len(x), len(y)
        if n1 < 2 or n2 < 2:
            raise XlRaise(E.DIV0)
        m1, m2, v1, v2 = math.fsum(x) / n1, math.fsum(y) / n2, statistics.variance(x), statistics.variance(y)
        if k == 2:
            sp = ((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)
            se = math.sqrt(sp * (1 / n1 + 1 / n2))
            df = n1 + n2 - 2.0
        else:
            se = math.sqrt(v1 / n1 + v2 / n2)
            df = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
        if se == 0:
            raise XlRaise(E.DIV0)
        t = (m1 - m2) / se
    p = 1 - S.t_cdf(abs(t), df)
    return p * tl


@fn("CHISQ.TEST", 2, 2, aliases=("CHITEST",), arr=True)
def f_chisq_test(ctx: Any, actual: Any, expected: Any) -> float:
    ra, re_ = matrix_rows(actual), matrix_rows(expected)
    if len(ra) != len(re_) or len(ra[0]) != len(re_[0]):
        raise XlRaise(E.NA)
    stat = 0.0
    for r1, r2 in zip(ra, re_, strict=True):
        for a, e in zip(r1, r2, strict=True):
            if not all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in (a, e)):
                raise XlRaise(E.VALUE)
            if e == 0:
                raise XlRaise(E.DIV0)
            stat += (a - e) ** 2 / e
    rows, cols = len(ra), len(ra[0])
    df = (rows - 1) * (cols - 1) if rows > 1 and cols > 1 else (rows * cols - 1)
    if df < 1:
        raise XlRaise(E.NA)
    return 1 - S.chi2_cdf(stat, df)


@fn("COMBINA", 2, 2)
def f_combina(ctx: Any, n: Any, k: Any) -> float:
    nn, kk = math.floor(num(ctx, n)), math.floor(num(ctx, k))
    _need(nn >= 0 and kk >= 0 and (nn > 0 or kk == 0))
    return 1.0 if kk == 0 else float(math.comb(nn + kk - 1, kk))


@fn("PERMUTATIONA", 2, 2)
def f_permutationa(ctx: Any, n: Any, k: Any) -> float:
    nn, kk = math.floor(num(ctx, n)), math.floor(num(ctx, k))
    _need(nn >= 0 and kk >= 0)
    return float(nn ** kk)


@fn("MULTINOMIAL", 1, -1)
def f_multinomial(ctx: Any, *args: Any) -> float:
    v = [math.floor(x) for x in numbers(args)]
    _need(all(x >= 0 for x in v))
    out = math.factorial(sum(v))
    for x in v:
        out //= math.factorial(x)
    return float(out)


_ = (boolean, XlError)
