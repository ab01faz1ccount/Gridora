"""Shared argument handling for function bodies."""
from __future__ import annotations

import math
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .. import xlerrors as E
from ..values import (
    Arr,
    RangeVal,
    Scalar,
    XlRaise,
    check,
    is_matrix,
    to_bool,
    to_int,
    to_num,
    to_str,
)
from ..xlerrors import XlError


def scalar(ctx: Any, v: Any) -> Scalar:
    return ctx.scalar(v)


def num(ctx: Any, v: Any) -> float:
    return to_num(ctx.scalar(v))


def text(ctx: Any, v: Any) -> str:
    return to_str(ctx.scalar(v))


def boolean(ctx: Any, v: Any) -> bool:
    return to_bool(ctx.scalar(v))


def integer(ctx: Any, v: Any) -> int:
    return to_int(ctx.scalar(v))


def opt_num(ctx: Any, v: Any, default: float) -> float:
    s = ctx.scalar(v)
    return default if s is None else to_num(s)


def matrix_rows(v: Any) -> list[list[Scalar]]:
    if isinstance(v, (Arr, RangeVal)):
        return v.to_rows()
    if isinstance(v, XlError):
        raise XlRaise(v)
    return [[v]]


def iter_cells(v: Any) -> Iterator[Scalar]:
    if isinstance(v, (Arr, RangeVal)):
        yield from v.iter_values()
    else:
        yield v


def numbers(args: tuple[Any, ...], *, count_text_in_refs: bool = False) -> Iterator[float]:
    """Numbers as SUM/AVERAGE/MAX see them: in matrices only real numbers (errors raise);
    direct arguments are coerced (text -> number or #VALUE!, TRUE -> 1)."""
    for a in args:
        if is_matrix(a):
            for x in a.iter_values():
                if isinstance(x, XlError):
                    raise XlRaise(x)
                if isinstance(x, bool):
                    if count_text_in_refs:
                        yield 1.0 if x else 0.0
                elif isinstance(x, (int, float)):
                    yield float(x)
                elif isinstance(x, str) and count_text_in_refs:
                    yield 0.0
        else:
            if a is None:
                yield 0.0
            else:
                yield to_num(check(a))


def round_half_up(x: float, digits: int) -> float:
    if math.isinf(x) or math.isnan(x):
        raise XlRaise(E.NUM)
    d = Decimal(repr(x))
    q = Decimal(1).scaleb(-digits)
    try:
        return float(d.quantize(q, rounding=ROUND_HALF_UP))
    except Exception:  # noqa: BLE001
        # huge digits / exponent overflow: value is already exact at that precision
        return x


def wildcard_to_regex(pat: str) -> str:
    import re

    out = []
    i = 0
    while i < len(pat):
        ch = pat[i]
        if ch == "~" and i + 1 < len(pat):
            out.append(re.escape(pat[i + 1]))
            i += 2
            continue
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)
