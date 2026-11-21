"""LET, LAMBDA and the lambda helper functions (MAP, REDUCE, SCAN, BYROW, BYCOL, MAKEARRAY)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import xlerrors as E
from ..parser import Name
from ..values import Arr, XlRaise
from ..xlerrors import XlError
from .helpers import integer, matrix_rows, scalar
from .registry import fn

if TYPE_CHECKING:
    from ..evaluator import Ctx, LambdaVal


def call_lambda(lam: Any, ctx: Any, args: list[Any]) -> Any:
    from ..evaluator import call_lambda as _call  # evaluator imports this package, so import late

    return _call(lam, ctx, args)


def _names(nodes: list[Any]) -> list[str]:
    out = []
    for n in nodes:
        if not isinstance(n, Name):
            raise XlRaise(E.VALUE)
        out.append(n.name.upper())
    return out


@fn("LET", 3, 253, lazy=True)
def f_let(ctx: Ctx, nodes: list[Any]) -> Any:
    if len(nodes) % 2 == 0:
        raise XlRaise(E.VALUE)
    scope = dict(ctx.scope or {})
    from ..evaluator import Ctx as _Ctx

    cur = _Ctx(ctx.env, ctx.sheet, ctx.row, ctx.col, ctx.arr, ctx.depth, scope)
    for i in range(0, len(nodes) - 1, 2):
        name = _names([nodes[i]])[0]
        scope[name] = cur.ev(nodes[i + 1])
    return cur.ev(nodes[-1])


@fn("LAMBDA", 1, 254, lazy=True)
def f_lambda(ctx: Ctx, nodes: list[Any]) -> LambdaVal:
    from ..evaluator import LambdaVal

    return LambdaVal(_names(nodes[:-1]), nodes[-1], ctx.scope)


def _lam(v: Any) -> LambdaVal:
    from ..evaluator import LambdaVal

    if isinstance(v, XlError):
        raise XlRaise(v)
    if not isinstance(v, LambdaVal):
        raise XlRaise(E.VALUE)
    return v


def _one(ctx: Ctx, v: Any) -> Any:
    return scalar(ctx, v)


@fn("MAP", 2, 254, arr=True)
def f_map(ctx: Ctx, *args: Any) -> Arr:
    lam = _lam(args[-1])
    mats = [matrix_rows(a) for a in args[:-1]]
    h, w = len(mats[0]), len(mats[0][0])
    if any(len(m) != h or len(m[0]) != w for m in mats):
        raise XlRaise(E.VALUE)
    return Arr([[_one(ctx, call_lambda(lam, ctx, [m[i][j] for m in mats])) for j in range(w)] for i in range(h)])


@fn("REDUCE", 3, 3, arr=True)
def f_reduce(ctx: Ctx, init: Any, a: Any, lam_v: Any) -> Any:
    lam = _lam(lam_v)
    acc = _one(ctx, init) if init is not None else None
    for row in matrix_rows(a):
        for v in row:
            acc = _one(ctx, call_lambda(lam, ctx, [acc, v]))
    return acc


@fn("SCAN", 3, 3, arr=True)
def f_scan(ctx: Ctx, init: Any, a: Any, lam_v: Any) -> Arr:
    lam = _lam(lam_v)
    acc = _one(ctx, init) if init is not None else None
    out = []
    for row in matrix_rows(a):
        r = []
        for v in row:
            acc = _one(ctx, call_lambda(lam, ctx, [acc, v]))
            r.append(acc)
        out.append(r)
    return Arr(out)


@fn("BYROW", 2, 2, arr=True)
def f_byrow(ctx: Ctx, a: Any, lam_v: Any) -> Arr:
    lam = _lam(lam_v)
    return Arr([[_one(ctx, call_lambda(lam, ctx, [Arr([row])]))] for row in matrix_rows(a)])


@fn("BYCOL", 2, 2, arr=True)
def f_bycol(ctx: Ctx, a: Any, lam_v: Any) -> Arr:
    lam = _lam(lam_v)
    cols = list(zip(*matrix_rows(a), strict=True))
    return Arr([[_one(ctx, call_lambda(lam, ctx, [Arr([[v] for v in col])])) for col in cols]])


@fn("MAKEARRAY", 3, 3, arr=True)
def f_makearray(ctx: Ctx, rows: Any, cols: Any, lam_v: Any) -> Arr:
    lam = _lam(lam_v)
    r, c = integer(ctx, scalar(ctx, rows)), integer(ctx, scalar(ctx, cols))
    if r < 1 or c < 1:
        raise XlRaise(E.VALUE)
    return Arr([[_one(ctx, call_lambda(lam, ctx, [float(i + 1), float(j + 1)])) for j in range(c)] for i in range(r)])
