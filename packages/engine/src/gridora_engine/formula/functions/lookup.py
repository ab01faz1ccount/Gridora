from __future__ import annotations

import re
from typing import Any

from .. import xlerrors as E
from ..refs import cell_text
from ..values import (
    Arr,
    RangeVal,
    Scalar,
    XlRaise,
    check,
    compare,
    is_matrix,
    to_bool,
    to_int,
    to_num,
    to_str,
)
from ..xlerrors import XlError
from .helpers import boolean, integer, matrix_rows, opt_num, scalar, text, wildcard_to_regex
from .registry import fn


def _kind(v: Scalar) -> int:
    if isinstance(v, bool):
        return 2
    if isinstance(v, str):
        return 1
    if isinstance(v, (int, float)):
        return 0
    return -1  # empty / error


def _cmp_same(a: Scalar, b: Scalar) -> int | None:
    ka, kb = _kind(a), _kind(b)
    if ka != kb or ka < 0:
        return None
    return compare(a, b)


def _vector(a: Any) -> list[Scalar]:
    if not is_matrix(a):
        return [a]
    if a.nrows != 1 and a.ncols != 1:
        raise XlRaise(E.NA)
    return list(a.iter_values())


def _exact_matcher(look: Scalar):
    if isinstance(look, str) and ("*" in look or "?" in look or "~" in look):
        rx = re.compile(wildcard_to_regex(look), re.IGNORECASE | re.DOTALL)
        return lambda v: isinstance(v, str) and rx.fullmatch(v) is not None
    return lambda v: _cmp_same(look, v) == 0


def _approx(values: list[Scalar], look: Scalar, mode: int) -> int:
    """Index of the match for MATCH-style type 1 (largest <=) or -1 (smallest >=); -1 if none."""
    best = -1
    for i, v in enumerate(values):
        c = _cmp_same(v, look)
        if c is None:
            continue
        if mode == 1:
            if c <= 0:
                best = i
            else:
                break
        else:
            if c >= 0:
                best = i
            else:
                break
    return best


@fn("MATCH", 2, 3)
def f_match(ctx: Any, look: Any, arr: Any, mt: Any = None) -> float:
    v = check(scalar(ctx, look))
    values = _vector(arr)
    mode = int(opt_num(ctx, mt, 1))
    if mode == 0:
        m = _exact_matcher(v)
        for i, x in enumerate(values):
            if m(x):
                return float(i + 1)
        raise XlRaise(E.NA)
    i = _approx(values, v, 1 if mode > 0 else -1)
    if i < 0:
        raise XlRaise(E.NA)
    return float(i + 1)


@fn("VLOOKUP", 3, 4)
def f_vlookup(ctx: Any, look: Any, table: Any, col: Any, rl: Any = None) -> Any:
    v = check(scalar(ctx, look))
    if not is_matrix(table):
        raise XlRaise(E.VALUE)
    ci = integer(ctx, col)
    if ci < 1:
        raise XlRaise(E.VALUE)
    if ci > table.ncols:
        raise XlRaise(E.REF)
    approx = True if rl is None else boolean(ctx, rl)
    keys = [table.at(i, 0) for i in range(table.nrows)]
    if not approx:
        m = _exact_matcher(v)
        for i, k in enumerate(keys):
            if m(k):
                return table.at(i, ci - 1)
        raise XlRaise(E.NA)
    i = _approx(keys, v, 1)
    if i < 0:
        raise XlRaise(E.NA)
    return table.at(i, ci - 1)


@fn("HLOOKUP", 3, 4)
def f_hlookup(ctx: Any, look: Any, table: Any, row: Any, rl: Any = None) -> Any:
    v = check(scalar(ctx, look))
    if not is_matrix(table):
        raise XlRaise(E.VALUE)
    ri = integer(ctx, row)
    if ri < 1:
        raise XlRaise(E.VALUE)
    if ri > table.nrows:
        raise XlRaise(E.REF)
    approx = True if rl is None else boolean(ctx, rl)
    keys = [table.at(0, j) for j in range(table.ncols)]
    if not approx:
        m = _exact_matcher(v)
        for j, k in enumerate(keys):
            if m(k):
                return table.at(ri - 1, j)
        raise XlRaise(E.NA)
    j = _approx(keys, v, 1)
    if j < 0:
        raise XlRaise(E.NA)
    return table.at(ri - 1, j)


@fn("LOOKUP", 2, 3)
def f_lookup(ctx: Any, look: Any, vec: Any, res: Any = None) -> Any:
    v = check(scalar(ctx, look))
    if res is None and is_matrix(vec) and vec.nrows > 1 and vec.ncols > 1:
        # array form: search first column (or row if wider), return last column (row)
        if vec.ncols >= vec.nrows:
            keys = [vec.at(0, j) for j in range(vec.ncols)]
            i = _approx(keys, v, 1)
            if i < 0:
                raise XlRaise(E.NA)
            return vec.at(vec.nrows - 1, i)
        keys = [vec.at(i, 0) for i in range(vec.nrows)]
        i = _approx(keys, v, 1)
        if i < 0:
            raise XlRaise(E.NA)
        return vec.at(i, vec.ncols - 1)
    keys = _vector(vec)
    i = _approx(keys, v, 1)
    if i < 0:
        raise XlRaise(E.NA)
    out = _vector(res) if res is not None else keys
    if i >= len(out):
        raise XlRaise(E.NA)
    return out[i]


@fn("INDEX", 2, 4, arr=True)
def f_index(ctx: Any, arr: Any, row: Any, col: Any = None, area: Any = None) -> Any:
    if isinstance(arr, XlError):
        raise XlRaise(arr)
    if not is_matrix(arr):
        arr = Arr([[arr]])
    r = integer(ctx, row)
    cexpr = col
    if cexpr is None:
        if arr.nrows == 1 and arr.ncols > 1:
            c, r = r, 0 if False else 1
            r_idx, c_idx = 1, c
        else:
            r_idx, c_idx = r, (0 if arr.ncols > 1 else 1)
            if arr.ncols == 1:
                c_idx = 1
    else:
        r_idx, c_idx = r, integer(ctx, cexpr)
    if r_idx < 0 or c_idx < 0 or r_idx > arr.nrows or c_idx > arr.ncols:
        raise XlRaise(E.REF)
    if isinstance(arr, RangeVal):
        r0 = arr.r0 + (r_idx - 1 if r_idx else 0)
        r1 = r0 if r_idx else arr.r1
        c0 = arr.c0 + (c_idx - 1 if c_idx else 0)
        c1 = c0 if c_idx else arr.c1
        return RangeVal(arr.env, arr.sheet, r0, c0, r1, c1)
    rows = arr.rows
    ri = range(arr.nrows) if r_idx == 0 else [r_idx - 1]
    cj = range(arr.ncols) if c_idx == 0 else [c_idx - 1]
    sub = [[rows[i][j] for j in cj] for i in ri]
    return sub[0][0] if len(sub) == 1 and len(sub[0]) == 1 else Arr(sub)


@fn("OFFSET", 3, 5, volatile=True)
def f_offset(ctx: Any, ref: Any, rows: Any, cols: Any, h: Any = None, w: Any = None) -> Any:
    if not isinstance(ref, RangeVal):
        raise XlRaise(E.VALUE)
    dr, dc = integer(ctx, rows), integer(ctx, cols)
    hh = ref.nrows if h is None else integer(ctx, h)
    ww = ref.ncols if w is None else integer(ctx, w)
    if hh < 1 or ww < 1:
        raise XlRaise(E.REF)
    r0, c0 = ref.r0 + dr, ref.c0 + dc
    if r0 < 0 or c0 < 0 or r0 + hh > 1_048_576 or c0 + ww > 16_384:
        raise XlRaise(E.REF)
    return RangeVal(ref.env, ref.sheet, r0, c0, r0 + hh - 1, c0 + ww - 1)


@fn("INDIRECT", 1, 2, volatile=True)
def f_indirect(ctx: Any, a: Any, a1: Any = None) -> Any:
    from ..evaluator import resolve_ref
    from ..parser import FormulaSyntaxError, Name, make_ref, tokenize

    s = text(ctx, a).strip()
    if a1 is not None and not boolean(ctx, a1):
        raise XlRaise(E.REF)  # R1C1 style is not supported
    try:
        toks = tokenize(s)
    except FormulaSyntaxError:
        raise XlRaise(E.REF) from None
    if len(toks) == 2 and toks[0].kind == "ref":
        sheet, area = toks[0].value
        try:
            ref = make_ref(sheet, area)
        except FormulaSyntaxError:
            raise XlRaise(E.REF) from None
        r = resolve_ref(ref, ctx)
        if isinstance(r, XlError):
            raise XlRaise(r)
        return r
    if len(toks) == 2 and toks[0].kind == "name":
        target = ctx.env.defined_name(toks[0].text, ctx.sheet)
        if target is None:
            raise XlRaise(E.REF)
        from ..evaluator import eval_name

        return eval_name(Name(toks[0].text), ctx)
    raise XlRaise(E.REF)


@fn("ADDRESS", 2, 5)
def f_address(ctx: Any, row: Any, col: Any, absn: Any = None, a1: Any = None, sheet: Any = None) -> str:
    r, c = integer(ctx, row), integer(ctx, col)
    kind = int(opt_num(ctx, absn, 1))
    if r < 1 or c < 1 or r > 1_048_576 or c > 16_384 or kind not in (1, 2, 3, 4):
        raise XlRaise(E.VALUE)
    if a1 is not None and not boolean(ctx, a1):
        s = f"R{r if kind in (1, 2) else '[' + str(r) + ']'}C{c if kind in (1, 3) else '[' + str(c) + ']'}"
    else:
        s = cell_text(r - 1, c - 1, kind in (1, 2), kind in (1, 3))
    if sheet is not None:
        name = text(ctx, sheet)
        s = (f"'{name}'" if re.search(r"[^\w\.]", name) else name) + "!" + s
    return s


# -- XLOOKUP / XMATCH ---------------------------------------------------------------------------------
def _xfind(ctx: Any, look: Scalar, values: list[Scalar], mode: int, search: int) -> int:
    idxs = range(len(values)) if search >= 0 else range(len(values) - 1, -1, -1)
    if mode == 2:
        rx = re.compile(wildcard_to_regex(to_str(look)), re.IGNORECASE | re.DOTALL)
        for i in idxs:
            x = values[i]
            if isinstance(x, str) and rx.fullmatch(x):
                return i
        return -1
    for i in idxs:
        if _cmp_same(look, values[i]) == 0:
            return i
    if mode == 0:
        return -1
    best, best_i = None, -1
    for i in idxs:
        c = _cmp_same(values[i], look)
        if c is None:
            continue
        if ((mode == -1 and c < 0) or (mode == 1 and c > 0)) and (
            best is None or (compare(values[i], best) > 0 if mode == -1 else compare(values[i], best) < 0)
        ):
            best, best_i = values[i], i
    return best_i


@fn("XMATCH", 2, 4)
def f_xmatch(ctx: Any, look: Any, arr: Any, mm: Any = None, sm: Any = None) -> float:
    v = check(scalar(ctx, look))
    values = _vector(arr)
    i = _xfind(ctx, v, values, int(opt_num(ctx, mm, 0)), int(opt_num(ctx, sm, 1)))
    if i < 0:
        raise XlRaise(E.NA)
    return float(i + 1)


@fn("XLOOKUP", 3, 6, lazy=True)
def f_xlookup(ctx: Any, nodes: list) -> Any:
    ev = ctx.ev
    v = check(scalar(ctx, ev(nodes[0])))
    look = ev(nodes[1], True)
    ret = ev(nodes[2], True)
    values = _vector(look)
    mm = int(to_num(scalar(ctx, ev(nodes[4])))) if len(nodes) > 4 and nodes[4].__class__.__name__ != "Missing" else 0
    sm = int(to_num(scalar(ctx, ev(nodes[5])))) if len(nodes) > 5 and nodes[5].__class__.__name__ != "Missing" else 1
    i = _xfind(ctx, v, values, mm, sm)
    if i < 0:
        if len(nodes) > 3 and nodes[3].__class__.__name__ != "Missing":
            return ev(nodes[3])
        raise XlRaise(E.NA)
    if not is_matrix(ret):
        return ret
    if look.nrows == 1 and look.ncols > 1 or (look.ncols == 1 and look.nrows == 1 and ret.nrows == 1):
        col = [ret.at(k, i) for k in range(ret.nrows)]
        return col[0] if len(col) == 1 else Arr([[x] for x in col])
    row = [ret.at(i, k) for k in range(ret.ncols)]
    return row[0] if len(row) == 1 else Arr([row])


# -- dynamic array helpers -----------------------------------------------------------------------------------
def _key(v: Scalar) -> Any:
    k = _kind(v)
    if k == 1:
        return (1, v.lower())
    if k == -1:
        return (-1, "")
    return (k, float(v))


@fn("UNIQUE", 1, 3, arr=True)
def f_unique(ctx: Any, a: Any, by_col: Any = None, once: Any = None) -> Arr:
    rows = matrix_rows(a)
    bc = by_col is not None and boolean(ctx, by_col)
    ex = once is not None and boolean(ctx, once)
    items = [list(c) for c in zip(*rows)] if bc else rows
    seen: dict[tuple, int] = {}
    order: list[tuple] = []
    for it in items:
        k = tuple(_key(x) for x in it)
        if k not in seen:
            seen[k] = 0
            order.append(k)
        seen[k] += 1
    out = []
    used: set[tuple] = set()
    for it in items:
        k = tuple(_key(x) for x in it)
        if k in used:
            continue
        used.add(k)
        if ex and seen[k] != 1:
            continue
        out.append(it)
    if not out:
        raise XlRaise(E.CALC)
    return Arr([list(c) for c in zip(*out)]) if bc else Arr(out)


@fn("SORT", 1, 4, arr=True)
def f_sort(ctx: Any, a: Any, idx: Any = None, order: Any = None, by_col: Any = None) -> Arr:
    rows = matrix_rows(a)
    bc = by_col is not None and boolean(ctx, by_col)
    items = [list(c) for c in zip(*rows)] if bc else [r[:] for r in rows]
    i = int(opt_num(ctx, idx, 1)) - 1
    desc = int(opt_num(ctx, order, 1)) == -1
    if i < 0 or (items and i >= len(items[0])):
        raise XlRaise(E.VALUE)
    items.sort(key=lambda it: _sort_key(it[i]), reverse=desc)
    return Arr([list(c) for c in zip(*items)]) if bc else Arr(items)


def _sort_key(v: Scalar):
    k = _kind(v)
    if k == -1:
        return (3, 0)
    if k == 1:
        return (1, v.lower())
    return (k, float(v))


@fn("SORTBY", 2, -1, arr=True)
def f_sortby(ctx: Any, a: Any, *rest: Any) -> Arr:
    rows = matrix_rows(a)
    keys: list[tuple[list[Scalar], bool]] = []
    i = 0
    while i < len(rest):
        kv = [x for row in matrix_rows(rest[i]) for x in row]
        if len(kv) != len(rows):
            raise XlRaise(E.VALUE)
        desc = False
        if i + 1 < len(rest) and not is_matrix(rest[i + 1]):
            desc = to_int(rest[i + 1]) == -1
            i += 1
        keys.append((kv, desc))
        i += 1
    order = list(range(len(rows)))
    for kv, desc in reversed(keys):
        order.sort(key=lambda r: _sort_key(kv[r]), reverse=desc)
    return Arr([rows[r][:] for r in order])


@fn("FILTER", 2, 3, arr=True)
def f_filter(ctx: Any, a: Any, inc: Any, empty: Any = None) -> Any:
    rows = matrix_rows(a)
    flags = [x for row in matrix_rows(inc) for x in row]
    if len(flags) == len(rows):
        out = [r for r, f in zip(rows, flags) if to_bool(check(f))]
    elif rows and len(flags) == len(rows[0]):
        keep = [j for j, f in enumerate(flags) if to_bool(check(f))]
        out = [[r[j] for j in keep] for r in rows] if keep else []
    else:
        raise XlRaise(E.VALUE)
    if not out or not out[0]:
        if empty is not None:
            return empty
        raise XlRaise(E.CALC)
    return Arr(out)


@fn("VSTACK", 1, -1, arr=True)
def f_vstack(ctx: Any, *args: Any) -> Arr:
    mats = [matrix_rows(a) for a in args]
    w = max(len(m[0]) for m in mats)
    out = []
    for m in mats:
        for row in m:
            out.append(row + [E.NA] * (w - len(row)))
    return Arr(out)


@fn("HSTACK", 1, -1, arr=True)
def f_hstack(ctx: Any, *args: Any) -> Arr:
    mats = [matrix_rows(a) for a in args]
    h = max(len(m) for m in mats)
    out = []
    for i in range(h):
        row: list[Scalar] = []
        for m in mats:
            row.extend(m[i] if i < len(m) else [E.NA] * len(m[0]))
        out.append(row)
    return Arr(out)
