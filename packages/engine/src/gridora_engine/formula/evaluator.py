"""Tree-walking evaluator. Talks to the workbook only through `Env`."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from . import xlerrors as E
from .functions import REGISTRY
from .parser import (
    ArrayLit,
    Binary,
    Bool,
    Err,
    FormulaSyntaxError,
    Func,
    Missing,
    Name,
    Node,
    Num,
    Percent,
    Ref,
    Str,
    Unary,
    parse,
)
from .values import (
    Arr,
    RangeVal,
    Scalar,
    XlRaise,
    compare,
    finite,
    to_num,
    to_str,
)
from .xlerrors import BY_CODE, XlError

MAX_ARRAY_CELLS = 1_000_000


class Env(Protocol):
    date1904: bool

    def sheet_index(self, name: str) -> int | None: ...
    def cell(self, sheet: int, r: int, c: int) -> Scalar: ...
    def used_size(self, sheet: int) -> tuple[int, int]: ...
    def defined_name(self, name: str, sheet: int) -> str | Ref | None: ...
    def now_serial(self) -> float: ...


@dataclass(slots=True)
class Ctx:
    env: Any
    sheet: int
    row: int
    col: int
    arr: bool = False
    depth: int = 0  # defined-name expansion depth

    # -- used by functions ------------------------------------------------------------------------
    def ev(self, node: Node, arr: bool | None = None) -> Any:
        return evaluate(node, self if arr is None or arr == self.arr else
                        Ctx(self.env, self.sheet, self.row, self.col, arr, self.depth))

    def scalar(self, v: Any) -> Scalar:
        return to_scalar(v, self)


def to_scalar(v: Any, ctx: Ctx) -> Scalar:
    """Collapse a range/array to one value: implicit intersection for single-row/column ranges
    (outside array context), otherwise the top-left cell."""
    if isinstance(v, RangeVal):
        if v.nrows == 0 or v.ncols == 0:
            return E.VALUE
        if v.nrows == 1 and v.ncols == 1:
            return v.at(0, 0)
        if not ctx.arr and v.sheet == ctx.sheet:
            if v.ncols == 1 and v.r0 <= ctx.row <= v.r1:
                return v.at(ctx.row - v.r0, 0)
            if v.nrows == 1 and v.c0 <= ctx.col <= v.c1:
                return v.at(0, ctx.col - v.c0)
            return E.VALUE
        if not ctx.arr:
            return E.VALUE
        return v.at(0, 0)
    if isinstance(v, Arr):
        return v.at(0, 0) if v.rows and v.rows[0] else E.VALUE
    return v


def final_value(v: Any, ctx: Ctx) -> Scalar:
    """Value stored in the formula cell (top-left of any matrix, as before spill support)."""
    if isinstance(v, RangeVal):
        return v.at(0, 0) if v.nrows and v.ncols else E.VALUE
    if isinstance(v, Arr):
        return v.at(0, 0) if v.rows and v.rows[0] else E.VALUE
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return E.NUM
    return v


# -- entry points ---------------------------------------------------------------------------------------
def evaluate_formula(node: Node, env: Env, sheet: int, row: int, col: int, *, array: bool = False) -> Scalar:
    ctx = Ctx(env, sheet, row, col, arr=array)
    try:
        v = evaluate(node, ctx)
    except XlRaise as e:
        return e.err
    except RecursionError:
        return E.CALC
    return final_value(v, ctx)


def evaluate_array_formula(node: Node, env: Env, sheet: int, row: int, col: int) -> Arr | Scalar:
    ctx = Ctx(env, sheet, row, col, arr=True)
    try:
        v = evaluate(node, ctx)
    except XlRaise as e:
        return e.err
    except RecursionError:
        return E.CALC
    if isinstance(v, RangeVal):
        return Arr(v.to_rows())
    return v


def parse_cached(text: str, _cache: dict[str, Node | None] = {}) -> Node | None:  # noqa: B006
    """Parse with a small process-wide memo; None when the text does not parse."""
    if text in _cache:
        return _cache[text]
    try:
        node: Node | None = parse(text)
    except FormulaSyntaxError:
        node = None
    if len(_cache) > 20000:
        _cache.clear()
    _cache[text] = node
    return node


# -- core ---------------------------------------------------------------------------------------------------
def evaluate(node: Node, ctx: Ctx) -> Any:
    t = type(node)
    if t is Num:
        return node.v
    if t is Str:
        return node.v
    if t is Bool:
        return node.v
    if t is Ref:
        return resolve_ref(node, ctx)
    if t is Binary:
        return eval_binary(node, ctx)
    if t is Func:
        return call_function(node, ctx)
    if t is Unary:
        v = to_scalar_or_arr(evaluate(node.x, ctx), ctx)
        if node.op == "-":
            return map_unary(v, lambda x: -to_num(x))
        return v
    if t is Percent:
        v = to_scalar_or_arr(evaluate(node.x, ctx), ctx)
        return map_unary(v, lambda x: to_num(x) / 100)
    if t is Err:
        return BY_CODE.get(node.code, E.VALUE)
    if t is ArrayLit:
        return Arr([[evaluate(c, ctx) for c in row] for row in node.rows])
    if t is Name:
        return eval_name(node, ctx)
    if t is Missing:
        return None
    raise XlRaise(E.VALUE)


def _raise(e: XlError) -> Any:
    raise XlRaise(e)


def eval_name(node: Name, ctx: Ctx) -> Any:
    n = node.name.upper()
    if n in ("TRUE", "FALSE"):
        return n == "TRUE"
    if ctx.depth > 16:
        return E.NAME
    target = ctx.env.defined_name(node.name, ctx.sheet)
    if target is None:
        return E.NAME
    if isinstance(target, str):
        parsed = parse_cached(target)
        if parsed is None:
            return E.NAME
        sub = Ctx(ctx.env, ctx.sheet, ctx.row, ctx.col, ctx.arr, ctx.depth + 1)
        return evaluate(parsed, sub)
    return resolve_ref(target, ctx)


def resolve_ref(ref: Ref, ctx: Ctx) -> Any:
    env = ctx.env
    if ref.sheet is None:
        sheet = ctx.sheet
    else:
        idx = env.sheet_index(ref.sheet)
        if idx is None:
            return E.REF
        sheet = idx
    rows, cols = env.used_size(sheet)
    r1 = ref.r1
    c1 = ref.c1
    nominal_r, nominal_c = ref.r1 - ref.r0 + 1, ref.c1 - ref.c0 + 1
    if ref.full_col or r1 >= rows:
        # Cells below the used area are empty; clamp so loops stay proportional to real data.
        r1 = min(r1, max(rows - 1, ref.r0))
    if ref.full_row or c1 >= cols:
        c1 = min(c1, max(cols - 1, ref.c0))
    return RangeVal(env, sheet, ref.r0, ref.c0, r1, c1, nominal_r, nominal_c)


def to_scalar_or_arr(v: Any, ctx: Ctx) -> Any:
    if isinstance(v, RangeVal):
        if ctx.arr:
            return Arr(v.to_rows())
        return to_scalar(v, ctx)
    return v


def map_unary(v: Any, f) -> Any:
    if isinstance(v, Arr):
        return Arr([[_safe(f, x) for x in row] for row in v.rows])
    return _safe(f, v)


def _safe(f, x):
    if isinstance(x, XlError):
        return x
    try:
        return f(x)
    except XlRaise as e:
        return e.err


# -- binary operators -------------------------------------------------------------------------------------
def eval_binary(node: Binary, ctx: Ctx) -> Any:
    op = node.op
    if op == ":":
        return eval_range_op(node, ctx)
    a = evaluate(node.a, ctx)
    b = evaluate(node.b, ctx)
    a = to_scalar_or_arr(a, ctx)
    b = to_scalar_or_arr(b, ctx)
    if isinstance(a, Arr) or isinstance(b, Arr):
        return broadcast(a, b, op)
    return apply_op(op, a, b)


def apply_op(op: str, a: Scalar, b: Scalar) -> Scalar:
    if isinstance(a, XlError):
        return a
    if isinstance(b, XlError):
        return b
    try:
        if op in ("+", "-", "*", "/", "^"):
            x, y = to_num(a), to_num(b)
            if op == "+":
                return finite(x + y)
            if op == "-":
                return finite(x - y)
            if op == "*":
                return finite(x * y)
            if op == "/":
                if y == 0:
                    return E.DIV0
                return finite(x / y)
            return power(x, y)
        if op == "&":
            return to_str(a) + to_str(b)
        cmp = compare(a, b)
        if op == "=":
            return cmp == 0
        if op == "<>":
            return cmp != 0
        if op == "<":
            return cmp < 0
        if op == ">":
            return cmp > 0
        if op == "<=":
            return cmp <= 0
        if op == ">=":
            return cmp >= 0
    except XlRaise as e:
        return e.err
    except OverflowError:
        return E.NUM
    return E.VALUE


def power(x: float, y: float) -> Scalar:
    if x == 0 and y == 0:
        return E.NUM
    if x == 0 and y < 0:
        return E.DIV0
    if x < 0 and y != int(y):
        return E.NUM
    try:
        r = x ** y
    except OverflowError:
        return E.NUM
    except ZeroDivisionError:
        return E.DIV0
    if isinstance(r, complex) or math.isnan(r) or math.isinf(r):
        return E.NUM
    return float(r)


def broadcast(a: Any, b: Any, op: str) -> Arr:
    ra = a.rows if isinstance(a, Arr) else [[a]]
    rb = b.rows if isinstance(b, Arr) else [[b]]
    na, ma = len(ra), len(ra[0]) if ra else 0
    nb, mb = len(rb), len(rb[0]) if rb else 0
    n, m = max(na, nb), max(ma, mb)
    if n * m > MAX_ARRAY_CELLS:
        raise XlRaise(E.VALUE)
    out: list[list[Scalar]] = []
    for i in range(n):
        row = []
        for j in range(m):
            x = _pick(ra, na, ma, i, j)
            y = _pick(rb, nb, mb, i, j)
            row.append(E.NA if x is _MISSING or y is _MISSING else apply_op(op, x, y))
        out.append(row)
    return Arr(out)


_MISSING = object()


def _pick(rows, n, m, i, j):
    ii = 0 if n == 1 else i
    jj = 0 if m == 1 else j
    if ii >= n or jj >= m:
        return _MISSING
    return rows[ii][jj]


def eval_range_op(node: Binary, ctx: Ctx) -> Any:
    a = evaluate(node.a, ctx)
    b = evaluate(node.b, ctx)
    if isinstance(a, XlError):
        return a
    if isinstance(b, XlError):
        return b
    if not (isinstance(a, RangeVal) and isinstance(b, RangeVal)) or a.sheet != b.sheet:
        return E.VALUE
    r0, c0 = min(a.r0, b.r0), min(a.c0, b.c0)
    r1, c1 = max(a.r1, b.r1), max(a.c1, b.c1)
    return RangeVal(a.env, a.sheet, r0, c0, r1, c1)


# -- function calls ------------------------------------------------------------------------------------------
def call_function(node: Func, ctx: Ctx) -> Any:
    spec = REGISTRY.get(node.name)
    if spec is None:
        return E.NAME
    n = len(node.args)
    if n < spec.min_args or (spec.max_args >= 0 and n > spec.max_args):
        return E.VALUE
    try:
        if spec.lazy:
            return spec.fn(ctx, node.args)
        sub = ctx if (not spec.arr or ctx.arr) else Ctx(ctx.env, ctx.sheet, ctx.row, ctx.col, True, ctx.depth)
        args = [evaluate(a, sub) for a in node.args]
        return spec.fn(sub, *args)
    except XlRaise as e:
        return e.err
    except (OverflowError, ValueError):
        return E.NUM
    except ZeroDivisionError:
        return E.DIV0
