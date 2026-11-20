from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable
from typing import Any

from .. import xlerrors as E
from ..values import Arr, RangeVal, Scalar, XlRaise, check, compare, finite, is_matrix, parse_number, to_bool, to_num
from ..xlerrors import XlError
from .helpers import integer, matrix_rows, num, numbers, opt_num, scalar, wildcard_to_regex
from .registry import fn


def _nums_in(args: tuple) -> list[float]:
    return list(numbers(args))


def _mat_numbers(a: Any) -> list[float]:
    """Numbers of one matrix argument, ignoring text/bool/empty; errors raise."""
    out = []
    for x in (a.iter_values() if is_matrix(a) else [a]):
        if isinstance(x, XlError):
            raise XlRaise(x)
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            out.append(float(x))
    return out


@fn("AVERAGE", 1, -1)
def f_average(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    if not v:
        raise XlRaise(E.DIV0)
    return math.fsum(v) / len(v)


@fn("AVERAGEA", 1, -1)
def f_averagea(ctx: Any, *args: Any) -> float:
    v = list(numbers(args, count_text_in_refs=True))
    if not v:
        raise XlRaise(E.DIV0)
    return math.fsum(v) / len(v)


@fn("MAX", 1, -1)
def f_max(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    return max(v) if v else 0.0


@fn("MIN", 1, -1)
def f_min(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    return min(v) if v else 0.0


@fn("MAXA", 1, -1)
def f_maxa(ctx: Any, *args: Any) -> float:
    v = list(numbers(args, count_text_in_refs=True))
    return max(v) if v else 0.0


@fn("MINA", 1, -1)
def f_mina(ctx: Any, *args: Any) -> float:
    v = list(numbers(args, count_text_in_refs=True))
    return min(v) if v else 0.0


@fn("COUNT", 1, -1)
def f_count(ctx: Any, *args: Any) -> float:
    n = 0
    for a in args:
        if is_matrix(a):
            n += sum(1 for x in a.iter_values() if isinstance(x, (int, float)) and not isinstance(x, bool))
        elif isinstance(a, XlError) or a is None:
            continue
        elif isinstance(a, bool) or isinstance(a, (int, float)):
            n += 1
        elif isinstance(a, str) and parse_number(a) is not None:
            n += 1
    return float(n)


@fn("COUNTA", 1, -1)
def f_counta(ctx: Any, *args: Any) -> float:
    n = 0
    for a in args:
        if is_matrix(a):
            n += sum(1 for x in a.iter_values() if x is not None)
        elif a is not None:
            n += 1
    return float(n)


@fn("COUNTBLANK", 1, 1)
def f_countblank(ctx: Any, a: Any) -> float:
    if not is_matrix(a):
        raise XlRaise(E.VALUE)
    total = (a.nominal_rows or a.nrows) * (a.nominal_cols or a.ncols) if isinstance(a, RangeVal) else a.nrows * a.ncols
    filled = sum(1 for x in a.iter_values() if x is not None and x != "")
    return float(total - filled)


@fn("MEDIAN", 1, -1)
def f_median(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    if not v:
        raise XlRaise(E.NUM)
    return float(statistics.median(v))


@fn("MODE", 1, -1, aliases=("MODE.SNGL",))
def f_mode(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    counts: dict[float, int] = {}
    for x in v:
        counts[x] = counts.get(x, 0) + 1
    best = max(counts.values(), default=0)
    if best < 2:
        raise XlRaise(E.NA)
    for x in v:  # first value that reaches the best count
        if counts[x] == best:
            return x
    raise XlRaise(E.NA)


@fn("LARGE", 2, 2)
def f_large(ctx: Any, a: Any, k: Any) -> float:
    v = sorted(_mat_numbers(a), reverse=True)
    n = math.ceil(num(ctx, k))
    if n < 1 or n > len(v):
        raise XlRaise(E.NUM)
    return v[n - 1]


@fn("SMALL", 2, 2)
def f_small(ctx: Any, a: Any, k: Any) -> float:
    v = sorted(_mat_numbers(a))
    n = math.ceil(num(ctx, k))
    if n < 1 or n > len(v):
        raise XlRaise(E.NUM)
    return v[n - 1]


@fn("RANK", 2, 3, aliases=("RANK.EQ",))
def f_rank(ctx: Any, x: Any, ref: Any, order: Any = None) -> float:
    n = num(ctx, x)
    v = _mat_numbers(ref)
    if n not in v:
        raise XlRaise(E.NA)
    asc = opt_num(ctx, order, 0) != 0
    return float(1 + sum(1 for y in v if (y < n if asc else y > n)))


@fn("RANK.AVG", 2, 3)
def f_rank_avg(ctx: Any, x: Any, ref: Any, order: Any = None) -> float:
    n = num(ctx, x)
    v = _mat_numbers(ref)
    if n not in v:
        raise XlRaise(E.NA)
    asc = opt_num(ctx, order, 0) != 0
    better = sum(1 for y in v if (y < n if asc else y > n))
    ties = sum(1 for y in v if y == n)
    return better + (ties + 1) / 2


def _var(v: list[float], sample: bool) -> float:
    n = len(v)
    if n < (2 if sample else 1):
        raise XlRaise(E.DIV0)
    m = math.fsum(v) / n
    return math.fsum((x - m) ** 2 for x in v) / (n - 1 if sample else n)


@fn("VAR", 1, -1, aliases=("VAR.S",))
def f_var(ctx: Any, *args: Any) -> float:
    return _var(_nums_in(args), True)


@fn("VARP", 1, -1, aliases=("VAR.P",))
def f_varp(ctx: Any, *args: Any) -> float:
    return _var(_nums_in(args), False)


@fn("STDEV", 1, -1, aliases=("STDEV.S",))
def f_stdev(ctx: Any, *args: Any) -> float:
    return math.sqrt(_var(_nums_in(args), True))


@fn("STDEVP", 1, -1, aliases=("STDEV.P",))
def f_stdevp(ctx: Any, *args: Any) -> float:
    return math.sqrt(_var(_nums_in(args), False))


@fn("DEVSQ", 1, -1)
def f_devsq(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    if not v:
        raise XlRaise(E.NUM)
    m = math.fsum(v) / len(v)
    return math.fsum((x - m) ** 2 for x in v)


@fn("AVEDEV", 1, -1)
def f_avedev(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    if not v:
        raise XlRaise(E.NUM)
    m = math.fsum(v) / len(v)
    return math.fsum(abs(x - m) for x in v) / len(v)


@fn("GEOMEAN", 1, -1)
def f_geomean(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    if not v or any(x <= 0 for x in v):
        raise XlRaise(E.NUM)
    return math.exp(math.fsum(math.log(x) for x in v) / len(v))


@fn("HARMEAN", 1, -1)
def f_harmean(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    if not v or any(x <= 0 for x in v):
        raise XlRaise(E.NUM)
    return len(v) / math.fsum(1 / x for x in v)


@fn("SKEW", 1, -1)
def f_skew(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    n = len(v)
    if n < 3:
        raise XlRaise(E.DIV0)
    m = sum(v) / n
    s = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    if s == 0:
        raise XlRaise(E.DIV0)
    return n / ((n - 1) * (n - 2)) * sum(((x - m) / s) ** 3 for x in v)


@fn("KURT", 1, -1)
def f_kurt(ctx: Any, *args: Any) -> float:
    v = _nums_in(args)
    n = len(v)
    if n < 4:
        raise XlRaise(E.DIV0)
    m = sum(v) / n
    s = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    if s == 0:
        raise XlRaise(E.DIV0)
    a = n * (n + 1) / ((n - 1) * (n - 2) * (n - 3)) * sum(((x - m) / s) ** 4 for x in v)
    return a - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))


def _percentile(v: list[float], k: float, inclusive: bool = True) -> float:
    v = sorted(v)
    n = len(v)
    if n == 0:
        raise XlRaise(E.NUM)
    if inclusive:
        if k < 0 or k > 1:
            raise XlRaise(E.NUM)
        pos = k * (n - 1)
    else:
        if k <= 0 or k >= 1:
            raise XlRaise(E.NUM)
        pos = k * (n + 1) - 1
        if pos < 0 or pos > n - 1:
            raise XlRaise(E.NUM)
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


@fn("PERCENTILE", 2, 2, aliases=("PERCENTILE.INC",))
def f_percentile(ctx: Any, a: Any, k: Any) -> float:
    return _percentile(_mat_numbers(a), num(ctx, k))


@fn("PERCENTILE.EXC", 2, 2)
def f_percentile_exc(ctx: Any, a: Any, k: Any) -> float:
    return _percentile(_mat_numbers(a), num(ctx, k), False)


@fn("QUARTILE", 2, 2, aliases=("QUARTILE.INC",))
def f_quartile(ctx: Any, a: Any, q: Any) -> float:
    qi = math.trunc(num(ctx, q))
    if qi < 0 or qi > 4:
        raise XlRaise(E.NUM)
    return _percentile(_mat_numbers(a), qi / 4)


@fn("QUARTILE.EXC", 2, 2)
def f_quartile_exc(ctx: Any, a: Any, q: Any) -> float:
    qi = math.trunc(num(ctx, q))
    if qi < 1 or qi > 3:
        raise XlRaise(E.NUM)
    return _percentile(_mat_numbers(a), qi / 4, False)


def _pairs(ys: Any, xs: Any) -> tuple[list[float], list[float]]:
    ry, rx = matrix_rows(ys), matrix_rows(xs)
    fy = [v for row in ry for v in row]
    fx = [v for row in rx for v in row]
    if len(fy) != len(fx):
        raise XlRaise(E.NA)
    py, px = [], []
    for a, b in zip(fy, fx):
        if isinstance(a, XlError):
            raise XlRaise(a)
        if isinstance(b, XlError):
            raise XlRaise(b)
        if all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in (a, b)):
            py.append(float(a))
            px.append(float(b))
    if len(py) < 2:
        raise XlRaise(E.DIV0)
    return py, px


@fn("CORREL", 2, 2, aliases=("PEARSON",))
def f_correl(ctx: Any, a: Any, b: Any) -> float:
    y, x = _pairs(a, b)
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((i - mx) ** 2 for i in x)
    syy = sum((i - my) ** 2 for i in y)
    if sxx == 0 or syy == 0:
        raise XlRaise(E.DIV0)
    return sum((i - mx) * (j - my) for i, j in zip(x, y)) / math.sqrt(sxx * syy)


@fn("RSQ", 2, 2)
def f_rsq(ctx: Any, a: Any, b: Any) -> float:
    return f_correl(ctx, a, b) ** 2


@fn("COVARIANCE.P", 2, 2, aliases=("COVAR",))
def f_covar_p(ctx: Any, a: Any, b: Any) -> float:
    y, x = _pairs(a, b)
    mx, my = sum(x) / len(x), sum(y) / len(y)
    return sum((i - mx) * (j - my) for i, j in zip(x, y)) / len(x)


@fn("COVARIANCE.S", 2, 2)
def f_covar_s(ctx: Any, a: Any, b: Any) -> float:
    y, x = _pairs(a, b)
    mx, my = sum(x) / len(x), sum(y) / len(y)
    return sum((i - mx) * (j - my) for i, j in zip(x, y)) / (len(x) - 1)


def _line(y: list[float], x: list[float]) -> tuple[float, float]:
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((i - mx) ** 2 for i in x)
    if sxx == 0:
        raise XlRaise(E.DIV0)
    slope = sum((i - mx) * (j - my) for i, j in zip(x, y)) / sxx
    return slope, my - slope * mx


@fn("SLOPE", 2, 2)
def f_slope(ctx: Any, ys: Any, xs: Any) -> float:
    y, x = _pairs(ys, xs)
    return _line(y, x)[0]


@fn("INTERCEPT", 2, 2)
def f_intercept(ctx: Any, ys: Any, xs: Any) -> float:
    y, x = _pairs(ys, xs)
    return _line(y, x)[1]


@fn("FORECAST", 3, 3, aliases=("FORECAST.LINEAR",))
def f_forecast(ctx: Any, x0: Any, ys: Any, xs: Any) -> float:
    y, x = _pairs(ys, xs)
    s, i = _line(y, x)
    return s * num(ctx, x0) + i


# -- distributions ----------------------------------------------------------------------------------
_N = statistics.NormalDist()


@fn("NORM.S.DIST", 2, 2)
def f_norm_s_dist(ctx: Any, z: Any, cum: Any) -> float:
    x = num(ctx, z)
    return _N.cdf(x) if to_bool(scalar(ctx, cum)) else _N.pdf(x)


@fn("NORMSDIST", 1, 1)
def f_normsdist(ctx: Any, z: Any) -> float:
    return _N.cdf(num(ctx, z))


@fn("NORM.DIST", 4, 4, aliases=("NORMDIST",))
def f_norm_dist(ctx: Any, x: Any, mu: Any, sd: Any, cum: Any) -> float:
    s = num(ctx, sd)
    if s <= 0:
        raise XlRaise(E.NUM)
    d = statistics.NormalDist(num(ctx, mu), s)
    return d.cdf(num(ctx, x)) if to_bool(scalar(ctx, cum)) else d.pdf(num(ctx, x))


@fn("NORM.S.INV", 1, 1, aliases=("NORMSINV",))
def f_norm_s_inv(ctx: Any, p: Any) -> float:
    q = num(ctx, p)
    if not 0 < q < 1:
        raise XlRaise(E.NUM)
    return _N.inv_cdf(q)


@fn("NORM.INV", 3, 3, aliases=("NORMINV",))
def f_norm_inv(ctx: Any, p: Any, mu: Any, sd: Any) -> float:
    q, s = num(ctx, p), num(ctx, sd)
    if not 0 < q < 1 or s <= 0:
        raise XlRaise(E.NUM)
    return statistics.NormalDist(num(ctx, mu), s).inv_cdf(q)


@fn("STANDARDIZE", 3, 3)
def f_standardize(ctx: Any, x: Any, mu: Any, sd: Any) -> float:
    s = num(ctx, sd)
    if s <= 0:
        raise XlRaise(E.NUM)
    return (num(ctx, x) - num(ctx, mu)) / s


# -- criteria functions -------------------------------------------------------------------------------
_OPS = ("<>", "<=", ">=", "=", "<", ">")


def make_matcher(criteria: Scalar) -> Callable[[Scalar], bool]:
    if isinstance(criteria, XlError):
        raise XlRaise(criteria)
    if criteria is None:
        return lambda v: v is None or v == 0
    if isinstance(criteria, bool):
        return lambda v: isinstance(v, bool) and v == criteria
    if isinstance(criteria, (int, float)):
        t = float(criteria)
        return lambda v: _numeq(v, t)
    s = str(criteria)
    op = "="
    for o in _OPS:
        if s.startswith(o):
            op, s = o, s[len(o):]
            break
    n = parse_number(s)
    if n is not None:
        return _numeric_op(op, n, s)
    u = s.upper()
    if u in ("TRUE", "FALSE") and op in ("=", "<>"):
        b = u == "TRUE"
        return (lambda v: isinstance(v, bool) and v == b) if op == "=" else (lambda v: not (isinstance(v, bool) and v == b))
    if s == "":
        if op == "=":
            return lambda v: v is None or v == ""
        if op == "<>":
            return lambda v: not (v is None or v == "")
    if "*" in s or "?" in s:
        rx = re.compile(wildcard_to_regex(s), re.I | re.S)
        if op == "=":
            return lambda v: isinstance(v, str) and rx.fullmatch(v) is not None
        if op == "<>":
            return lambda v: not (isinstance(v, str) and rx.fullmatch(v) is not None)
    low = s.lower()
    if op == "=":
        return lambda v: isinstance(v, str) and v.lower() == low
    if op == "<>":
        return lambda v: not (isinstance(v, str) and v.lower() == low)
    cmpf = {"<": lambda c: c < 0, ">": lambda c: c > 0, "<=": lambda c: c <= 0, ">=": lambda c: c >= 0}[op]
    return lambda v: isinstance(v, str) and cmpf((v.lower() > low) - (v.lower() < low))


def _numeq(v: Scalar, t: float) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return float(v) == t
    if isinstance(v, str):
        n = parse_number(v)
        return n is not None and n == t
    return False


def _numeric_op(op: str, n: float, raw: str) -> Callable[[Scalar], bool]:
    def isnum(v: Scalar) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    if op == "=":
        return lambda v: _numeq(v, n)
    if op == "<>":
        return lambda v: not _numeq(v, n)
    f = {"<": lambda x: x < n, ">": lambda x: x > n, "<=": lambda x: x <= n, ">=": lambda x: x >= n}[op]
    return lambda v: isnum(v) and f(float(v))


def _crit_pairs(ctx: Any, args: tuple) -> list[tuple[Any, Callable[[Scalar], bool]]]:
    if len(args) % 2:
        raise XlRaise(E.VALUE)
    out = []
    shape = None
    for i in range(0, len(args), 2):
        rng = args[i]
        if not is_matrix(rng):
            raise XlRaise(E.VALUE)
        sh = (rng.nrows, rng.ncols)
        if shape is None:
            shape = sh
        elif sh != shape:
            raise XlRaise(E.VALUE)
        out.append((rng, make_matcher(scalar(ctx, args[i + 1]))))
    return out


def _matching_cells(pairs: list[tuple[Any, Callable[[Scalar], bool]]]):
    """Yield (i, j) of every cell position that satisfies all criteria."""
    first = pairs[0][0]
    cols = [(r.to_rows(), m) for r, m in pairs]
    for i in range(first.nrows):
        for j in range(first.ncols):
            if all(m(rows[i][j]) for rows, m in cols):
                yield i, j


@fn("COUNTIF", 2, 2)
def f_countif(ctx: Any, rng: Any, crit: Any) -> float:
    if not is_matrix(rng):
        raise XlRaise(E.VALUE)
    m = make_matcher(scalar(ctx, crit))
    return float(sum(1 for v in rng.iter_values() if m(v)))


@fn("COUNTIFS", 2, -1)
def f_countifs(ctx: Any, *args: Any) -> float:
    pairs = _crit_pairs(ctx, args)
    return float(sum(1 for _ in _matching_cells(pairs)))


def _sum_range(sum_rng: Any, first: Any) -> list[list[Scalar]]:
    if not is_matrix(sum_rng):
        raise XlRaise(E.VALUE)
    rows = sum_rng.to_rows()
    # A smaller/larger sum range is anchored at its top-left corner and takes the criteria range's size.
    n, m = first.nrows, first.ncols
    out = [[(rows[i][j] if i < len(rows) and j < len(rows[0]) else None) for j in range(m)] for i in range(n)]
    return out


def _agg_if(ctx: Any, sum_rng: Any, pairs, fnc):
    vals = _sum_range(sum_rng, pairs[0][0])
    picked: list[float] = []
    for i, j in _matching_cells(pairs):
        x = vals[i][j]
        if isinstance(x, XlError):
            raise XlRaise(x)
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            picked.append(float(x))
    return fnc(picked)


@fn("SUMIF", 2, 3)
def f_sumif(ctx: Any, rng: Any, crit: Any, sum_rng: Any = None) -> float:
    if not is_matrix(rng):
        raise XlRaise(E.VALUE)
    pairs = [(rng, make_matcher(scalar(ctx, crit)))]
    return _agg_if(ctx, rng if sum_rng is None else sum_rng, pairs, lambda v: math.fsum(v))


@fn("SUMIFS", 3, -1)
def f_sumifs(ctx: Any, sum_rng: Any, *args: Any) -> float:
    pairs = _crit_pairs(ctx, args)
    if (sum_rng.nrows, sum_rng.ncols) != (pairs[0][0].nrows, pairs[0][0].ncols):
        raise XlRaise(E.VALUE)
    return _agg_if(ctx, sum_rng, pairs, lambda v: math.fsum(v))


@fn("AVERAGEIF", 2, 3)
def f_averageif(ctx: Any, rng: Any, crit: Any, avg_rng: Any = None) -> float:
    if not is_matrix(rng):
        raise XlRaise(E.VALUE)
    pairs = [(rng, make_matcher(scalar(ctx, crit)))]

    def avg(v: list[float]) -> float:
        if not v:
            raise XlRaise(E.DIV0)
        return math.fsum(v) / len(v)

    return _agg_if(ctx, rng if avg_rng is None else avg_rng, pairs, avg)


@fn("AVERAGEIFS", 3, -1)
def f_averageifs(ctx: Any, avg_rng: Any, *args: Any) -> float:
    pairs = _crit_pairs(ctx, args)

    def avg(v: list[float]) -> float:
        if not v:
            raise XlRaise(E.DIV0)
        return math.fsum(v) / len(v)

    return _agg_if(ctx, avg_rng, pairs, avg)


@fn("MAXIFS", 3, -1)
def f_maxifs(ctx: Any, rng: Any, *args: Any) -> float:
    return _agg_if(ctx, rng, _crit_pairs(ctx, args), lambda v: max(v) if v else 0.0)


@fn("MINIFS", 3, -1)
def f_minifs(ctx: Any, rng: Any, *args: Any) -> float:
    return _agg_if(ctx, rng, _crit_pairs(ctx, args), lambda v: min(v) if v else 0.0)
