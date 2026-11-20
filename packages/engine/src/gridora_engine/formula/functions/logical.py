from __future__ import annotations

from typing import Any

from .. import xlerrors as E
from ..values import Arr, RangeVal, XlRaise, check, compare, is_matrix, to_bool
from ..xlerrors import XlError
from .helpers import boolean, iter_cells
from .registry import fn


@fn("IF", 2, 3, lazy=True)
def f_if(ctx: Any, nodes: list) -> Any:
    cond = ctx.ev(nodes[0])
    if isinstance(cond, (Arr, RangeVal)) and ctx.arr:
        return _if_array(ctx, nodes, cond)
    c = to_bool(check(ctx.scalar(cond)))
    if c:
        return ctx.ev(nodes[1])
    if len(nodes) == 3:
        return ctx.ev(nodes[2])
    return False


def _if_array(ctx: Any, nodes: list, cond: Any) -> Arr:
    rows = cond.to_rows()
    a = ctx.ev(nodes[1])
    b = ctx.ev(nodes[2]) if len(nodes) == 3 else False

    def pick(v, i, j):
        if isinstance(v, (Arr, RangeVal)):
            ii = 0 if v.nrows == 1 else i
            jj = 0 if v.ncols == 1 else j
            if ii >= v.nrows or jj >= v.ncols:
                return E.NA
            return v.at(ii, jj)
        return v

    out = []
    for i, row in enumerate(rows):
        orow = []
        for j, c in enumerate(row):
            if isinstance(c, XlError):
                orow.append(c)
                continue
            try:
                orow.append(pick(a, i, j) if to_bool(c) else pick(b, i, j))
            except XlRaise as e:
                orow.append(e.err)
        out.append(orow)
    return Arr(out)


@fn("IFERROR", 2, 2, lazy=True)
def f_iferror(ctx: Any, nodes: list) -> Any:
    v = ctx.ev(nodes[0])
    s = v if is_matrix(v) and ctx.arr else ctx.scalar(v)
    if isinstance(s, XlError):
        return ctx.ev(nodes[1])
    if isinstance(s, (Arr, RangeVal)):
        alt = ctx.ev(nodes[1])
        return Arr([[(alt if isinstance(x, XlError) else x) for x in row] for row in s.to_rows()])
    return s


@fn("IFNA", 2, 2, lazy=True)
def f_ifna(ctx: Any, nodes: list) -> Any:
    s = ctx.scalar(ctx.ev(nodes[0]))
    if s == E.NA:
        return ctx.ev(nodes[1])
    return s


@fn("IFS", 2, -1, lazy=True)
def f_ifs(ctx: Any, nodes: list) -> Any:
    if len(nodes) % 2:
        raise XlRaise(E.VALUE)
    for i in range(0, len(nodes), 2):
        if to_bool(check(ctx.scalar(ctx.ev(nodes[i])))):
            return ctx.ev(nodes[i + 1])
    raise XlRaise(E.NA)


def _bools(args: tuple) -> list[bool]:
    out: list[bool] = []
    seen = False
    for a in args:
        if is_matrix(a):
            for x in a.iter_values():
                if isinstance(x, XlError):
                    raise XlRaise(x)
                if isinstance(x, bool):
                    out.append(x)
                    seen = True
                elif isinstance(x, (int, float)):
                    out.append(x != 0)
                    seen = True
        else:
            if isinstance(a, XlError):
                raise XlRaise(a)
            if a is None:
                continue
            out.append(to_bool(a))
            seen = True
    if not seen:
        raise XlRaise(E.VALUE)
    return out


@fn("AND", 1, -1)
def f_and(ctx: Any, *args: Any) -> bool:
    return all(_bools(args))


@fn("OR", 1, -1)
def f_or(ctx: Any, *args: Any) -> bool:
    return any(_bools(args))


@fn("XOR", 1, -1)
def f_xor(ctx: Any, *args: Any) -> bool:
    return sum(_bools(args)) % 2 == 1


@fn("NOT", 1, 1)
def f_not(ctx: Any, a: Any) -> bool:
    return not boolean(ctx, a)


@fn("TRUE", 0, 0)
def f_true(ctx: Any) -> bool:
    return True


@fn("FALSE", 0, 0)
def f_false(ctx: Any) -> bool:
    return False


@fn("SWITCH", 3, -1, lazy=True)
def f_switch(ctx: Any, nodes: list) -> Any:
    target = check(ctx.scalar(ctx.ev(nodes[0])))
    rest = nodes[1:]
    pairs, default = (rest, None) if len(rest) % 2 == 0 else (rest[:-1], rest[-1])
    for i in range(0, len(pairs), 2):
        v = check(ctx.scalar(ctx.ev(pairs[i])))
        if compare(target, v) == 0:
            return ctx.ev(pairs[i + 1])
    if default is not None:
        return ctx.ev(default)
    raise XlRaise(E.NA)


@fn("CHOOSE", 2, -1, lazy=True)
def f_choose(ctx: Any, nodes: list) -> Any:
    from ..values import to_int

    i = to_int(check(ctx.scalar(ctx.ev(nodes[0]))))
    if i < 1 or i >= len(nodes):
        raise XlRaise(E.VALUE)
    return ctx.ev(nodes[i])
