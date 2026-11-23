"""Dynamic-array shaping, regression arrays, FREQUENCY and the D* database functions (E7)."""
from __future__ import annotations

import math
import statistics
from typing import Any

from .. import xlerrors as E
from ..values import Arr, Scalar, XlRaise, to_str
from ..xlerrors import XlError
from .helpers import boolean, integer, matrix_rows, num, scalar, text
from .registry import fn
from .stats import make_matcher


def _rows(a: Any) -> list[list[Scalar]]:
    if isinstance(a, XlError):
        raise XlRaise(a)
    return matrix_rows(a)


def _size(m: list[list[Scalar]]) -> tuple[int, int]:
    return len(m), (len(m[0]) if m else 0)


def _idx(n: int, k: int) -> tuple[int, int]:
    """Slice bounds for TAKE (k rows/cols; negative counts from the end)."""
    return (0, min(k, n)) if k >= 0 else (max(n + k, 0), n)


@fn("TAKE", 2, 3, arr=True)
def f_take(ctx: Any, a: Any, rows: Any, cols: Any = None) -> Arr:
    m = _rows(a)
    h, w = _size(m)
    r = integer(ctx, scalar(ctx, rows)) if rows is not None else h
    c = integer(ctx, scalar(ctx, cols)) if cols is not None else w
    if r == 0 or c == 0:
        raise XlRaise(E.CALC)
    r0, r1 = _idx(h, r)
    c0, c1 = _idx(w, c)
    return Arr([row[c0:c1] for row in m[r0:r1]])


@fn("DROP", 2, 3, arr=True)
def f_drop(ctx: Any, a: Any, rows: Any, cols: Any = None) -> Arr:
    m = _rows(a)
    h, w = _size(m)
    r = integer(ctx, scalar(ctx, rows)) if rows is not None else 0
    c = integer(ctx, scalar(ctx, cols)) if cols is not None else 0
    r0, r1 = (min(r, h), h) if r >= 0 else (0, max(h + r, 0))
    c0, c1 = (min(c, w), w) if c >= 0 else (0, max(w + c, 0))
    out = [row[c0:c1] for row in m[r0:r1]]
    if not out or not out[0]:
        raise XlRaise(E.CALC)
    return Arr(out)


def _pick(ctx: Any, args: tuple[Any, ...], n: int) -> list[int]:
    out = []
    for a in args:
        for row in _rows(a):
            for v in row:
                k = integer(ctx, v)
                if k == 0 or abs(k) > n:
                    raise XlRaise(E.VALUE)
                out.append(k - 1 if k > 0 else n + k)
    return out


@fn("CHOOSECOLS", 2, -1, arr=True)
def f_choosecols(ctx: Any, a: Any, *cols: Any) -> Arr:
    m = _rows(a)
    idx = _pick(ctx, cols, _size(m)[1])
    return Arr([[row[i] for i in idx] for row in m])


@fn("CHOOSEROWS", 2, -1, arr=True)
def f_chooserows(ctx: Any, a: Any, *rows: Any) -> Arr:
    m = _rows(a)
    idx = _pick(ctx, rows, _size(m)[0])
    return Arr([list(m[i]) for i in idx])


@fn("EXPAND", 2, 4, arr=True)
def f_expand(ctx: Any, a: Any, rows: Any, cols: Any = None, pad: Any = None) -> Arr:
    m = _rows(a)
    h, w = _size(m)
    r = integer(ctx, scalar(ctx, rows)) if rows is not None else h
    c = integer(ctx, scalar(ctx, cols)) if cols is not None else w
    if r < h or c < w:
        raise XlRaise(E.VALUE)
    fill = E.NA if pad is None else scalar(ctx, pad)
    return Arr([[(m[i][j] if i < h and j < w else fill) for j in range(c)] for i in range(r)])


def _flat(m: list[list[Scalar]], ignore: int, by_col: bool) -> list[Scalar]:
    cells = [v for col in zip(*m) for v in col] if by_col else [v for row in m for v in row]
    out = []
    for v in cells:
        if ignore in (1, 3) and (v is None):
            continue
        if ignore in (2, 3) and isinstance(v, XlError):
            continue
        out.append(v)
    if not out:
        raise XlRaise(E.CALC)
    return out


@fn("TOCOL", 1, 3, arr=True)
def f_tocol(ctx: Any, a: Any, ignore: Any = None, by_col: Any = None) -> Arr:
    ig = 0 if ignore is None else integer(ctx, scalar(ctx, ignore))
    bc = by_col is not None and boolean(ctx, scalar(ctx, by_col))
    return Arr([[v] for v in _flat(_rows(a), ig, bc)])


@fn("TOROW", 1, 3, arr=True)
def f_torow(ctx: Any, a: Any, ignore: Any = None, by_col: Any = None) -> Arr:
    ig = 0 if ignore is None else integer(ctx, scalar(ctx, ignore))
    bc = by_col is not None and boolean(ctx, scalar(ctx, by_col))
    return Arr([_flat(_rows(a), ig, bc)])


def _wrap(ctx: Any, a: Any, n: Any, pad: Any, *, by_row: bool) -> Arr:
    m = _rows(a)
    h, w = _size(m)
    if h != 1 and w != 1:
        raise XlRaise(E.VALUE)
    k = integer(ctx, scalar(ctx, n))
    if k < 1:
        raise XlRaise(E.NUM)
    vals = [v for row in m for v in row]
    fill = E.NA if pad is None else scalar(ctx, pad)
    chunks = [vals[i: i + k] for i in range(0, len(vals), k)]
    for ch in chunks:
        ch.extend([fill] * (k - len(ch)))
    return Arr(chunks) if by_row else Arr([list(r) for r in zip(*chunks)])


@fn("WRAPROWS", 2, 3, arr=True)
def f_wraprows(ctx: Any, a: Any, n: Any, pad: Any = None) -> Arr:
    return _wrap(ctx, a, n, pad, by_row=True)


@fn("WRAPCOLS", 2, 3, arr=True)
def f_wrapcols(ctx: Any, a: Any, n: Any, pad: Any = None) -> Arr:
    return _wrap(ctx, a, n, pad, by_row=False)


@fn("FREQUENCY", 2, 2, arr=True)
def f_frequency(ctx: Any, data: Any, bins: Any) -> Arr:
    def nums(a: Any) -> list[float]:
        out = []
        for row in _rows(a):
            for v in row:
                if isinstance(v, XlError):
                    raise XlRaise(v)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(float(v))
        return out

    d, b = nums(data), nums(bins)
    counts = [0.0] * (len(b) + 1)
    order = sorted(range(len(b)), key=lambda i: b[i])
    for x in d:
        slot = len(b)
        for i in order:
            if x <= b[i]:
                slot = i
                break
        counts[slot] += 1
    return Arr([[c] for c in counts])


# -- TREND / GROWTH (one independent variable) -----------------------------------------------------------
def _xy(ctx: Any, ys: Any, xs: Any) -> tuple[list[float], list[float]]:
    y = [v for r in _rows(ys) for v in r]
    if any(isinstance(v, XlError) for v in y):
        raise XlRaise(next(v for v in y if isinstance(v, XlError)))
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in y):
        raise XlRaise(E.VALUE)
    if xs is None:
        x = [float(i + 1) for i in range(len(y))]
    else:
        x = [v for r in _rows(xs) for v in r]
        if len(x) != len(y):
            raise XlRaise(E.NA)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in x):
            raise XlRaise(E.VALUE)
    return [float(v) for v in y], [float(v) for v in x]


def _fit(x: list[float], y: list[float], const: bool) -> tuple[float, float]:
    n = len(x)
    if n < 1:
        raise XlRaise(E.VALUE)
    if const:
        mx, my = math.fsum(x) / n, math.fsum(y) / n
        sxx = math.fsum((a - mx) ** 2 for a in x)
        if sxx == 0:
            raise XlRaise(E.NUM)
        s = math.fsum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sxx
        return s, my - s * mx
    sxx = math.fsum(a * a for a in x)
    if sxx == 0:
        raise XlRaise(E.NUM)
    return math.fsum(a * b for a, b in zip(x, y, strict=True)) / sxx, 0.0


def _newx(ctx: Any, new_x: Any, x: list[float], like: Any) -> list[list[float]]:
    if new_x is None:
        return [[v] for v in x] if len(_rows(like)[0]) == 1 else [x]
    rows = _rows(new_x)
    out = []
    for r in rows:
        row = []
        for v in r:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise XlRaise(E.VALUE)
            row.append(float(v))
        out.append(row)
    return out


@fn("TREND", 1, 4, arr=True)
def f_trend(ctx: Any, ys: Any, xs: Any = None, new_x: Any = None, const: Any = None) -> Arr:
    y, x = _xy(ctx, ys, xs)
    s, i = _fit(x, y, True if const is None else boolean(ctx, scalar(ctx, const)))
    return Arr([[s * v + i for v in r] for r in _newx(ctx, new_x, x, ys)])


@fn("GROWTH", 1, 4, arr=True)
def f_growth(ctx: Any, ys: Any, xs: Any = None, new_x: Any = None, const: Any = None) -> Arr:
    y, x = _xy(ctx, ys, xs)
    if any(v <= 0 for v in y):
        raise XlRaise(E.NUM)
    s, i = _fit(x, [math.log(v) for v in y], True if const is None else boolean(ctx, scalar(ctx, const)))
    return Arr([[math.exp(s * v + i) for v in r] for r in _newx(ctx, new_x, x, ys)])


# -- D* database functions -------------------------------------------------------------------------------
def _db(ctx: Any, database: Any, field: Any, criteria: Any) -> tuple[list[Scalar], list[list[Scalar]]]:
    db, cr = _rows(database), _rows(criteria)
    if len(db) < 1 or len(cr) < 1:
        raise XlRaise(E.VALUE)
    heads = [to_str(h).lower() if h is not None else "" for h in db[0]]
    f = scalar(ctx, field)
    if isinstance(f, XlError):
        raise XlRaise(f)
    if isinstance(f, (int, float)) and not isinstance(f, bool):
        k = int(f) - 1
        if not 0 <= k < len(heads):
            raise XlRaise(E.VALUE)
    else:
        name = to_str(f).lower()
        if name not in heads:
            raise XlRaise(E.VALUE)
        k = heads.index(name)
    chead = [to_str(h).lower() if h is not None else "" for h in cr[0]]
    groups = []
    for row in cr[1:]:
        conds = []
        for h, cell in zip(chead, row, strict=False):
            if cell is None or cell == "":
                continue
            if h not in heads:
                raise XlRaise(E.VALUE)
            conds.append((heads.index(h), make_matcher(cell)))
        groups.append(conds)
    matched = []
    for rec in db[1:]:
        if not groups or any(all(m(rec[j]) for j, m in g) for g in groups):
            matched.append(rec[k])
    return matched, db


def _dnums(vals: list[Scalar]) -> list[float]:
    out = []
    for v in vals:
        if isinstance(v, XlError):
            raise XlRaise(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    return out


def _dfn(name: str, body: Any, *, empty: XlError | None = None) -> None:
    @fn(name, 3, 3, arr=True)
    def _f(ctx: Any, database: Any, field: Any, criteria: Any) -> Any:
        vals, _ = _db(ctx, database, field, criteria)
        n = _dnums(vals)
        if not n and empty is not None:
            raise XlRaise(empty)
        return body(n, vals)


_dfn("DSUM", lambda n, v: math.fsum(n))
_dfn("DAVERAGE", lambda n, v: math.fsum(n) / len(n), empty=E.DIV0)
_dfn("DCOUNT", lambda n, v: float(len(n)))
_dfn("DCOUNTA", lambda n, v: float(sum(1 for x in v if x is not None and x != "")))
_dfn("DMAX", lambda n, v: max(n) if n else 0.0)
_dfn("DMIN", lambda n, v: min(n) if n else 0.0)
_dfn("DPRODUCT", lambda n, v: math.prod(n) if n else 0.0)
_dfn("DSTDEV", lambda n, v: statistics.stdev(n) if len(n) > 1 else (_ for _ in ()).throw(XlRaise(E.DIV0)))
_dfn("DSTDEVP", lambda n, v: statistics.pstdev(n), empty=E.DIV0)
_dfn("DVAR", lambda n, v: statistics.variance(n) if len(n) > 1 else (_ for _ in ()).throw(XlRaise(E.DIV0)))
_dfn("DVARP", lambda n, v: statistics.pvariance(n), empty=E.DIV0)


@fn("DGET", 3, 3, arr=True)
def f_dget(ctx: Any, database: Any, field: Any, criteria: Any) -> Scalar:
    vals, _ = _db(ctx, database, field, criteria)
    if not vals:
        raise XlRaise(E.VALUE)
    if len(vals) > 1:
        raise XlRaise(E.NUM)
    return vals[0]


@fn("VALUETOTEXT", 1, 2, arr=True)
def f_valuetotext(ctx: Any, v: Any, fmt: Any = None) -> str:
    s = scalar(ctx, v) if not isinstance(v, Arr) else v.rows[0][0]
    strict = fmt is not None and integer(ctx, scalar(ctx, fmt)) == 1
    return f'"{s}"' if strict and isinstance(s, str) else to_str(s)


@fn("ARRAYTOTEXT", 1, 2, arr=True)
def f_arraytotext(ctx: Any, a: Any, fmt: Any = None) -> str:
    strict = fmt is not None and integer(ctx, scalar(ctx, fmt)) == 1
    m = _rows(a)

    def one(v: Scalar) -> str:
        return f'"{v}"' if strict and isinstance(v, str) else to_str(v)

    if strict:
        return "{" + ";".join(",".join(one(v) for v in r) for r in m) + "}"
    return ", ".join(one(v) for r in m for v in r)


_ = (num, text)
