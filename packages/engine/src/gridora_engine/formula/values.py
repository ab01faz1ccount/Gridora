"""Evaluation values, matrices and Excel coercion rules.

Scalar values are plain Python objects: None (empty), float, str, bool, XlError.
Matrices (ranges and array constants) expose nrows / ncols / at(i, j).
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterator
from typing import Any

from . import xlerrors as E
from .xlerrors import XlError

Scalar = Any  # None | float | str | bool | XlError


class XlRaise(Exception):
    """Raised inside function bodies to return an error value; caught by the evaluator."""

    def __init__(self, err: XlError) -> None:
        self.err = err


class Arr:
    """Array constant or computed array (row-major list of rows)."""

    __slots__ = ("rows",)

    def __init__(self, rows: list[list[Scalar]]) -> None:
        self.rows = rows

    @property
    def nrows(self) -> int:
        return len(self.rows)

    @property
    def ncols(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    def at(self, i: int, j: int) -> Scalar:
        return self.rows[i][j]

    def iter_values(self) -> Iterator[Scalar]:
        for row in self.rows:
            yield from row

    def to_rows(self) -> list[list[Scalar]]:
        return self.rows


class RangeVal:
    """A rectangle of a sheet, read lazily through the environment."""

    __slots__ = ("env", "sheet", "r0", "c0", "r1", "c1", "nominal_rows", "nominal_cols")

    def __init__(self, env: Any, sheet: int, r0: int, c0: int, r1: int, c1: int,
                 nominal_rows: int | None = None, nominal_cols: int | None = None) -> None:
        self.env, self.sheet = env, sheet
        self.r0, self.c0, self.r1, self.c1 = r0, c0, r1, c1  # r1/c1 may be clamped to the used area
        self.nominal_rows = nominal_rows
        self.nominal_cols = nominal_cols

    @property
    def nrows(self) -> int:
        return max(self.r1 - self.r0 + 1, 0)

    @property
    def ncols(self) -> int:
        return max(self.c1 - self.c0 + 1, 0)

    def at(self, i: int, j: int) -> Scalar:
        return self.env.cell(self.sheet, self.r0 + i, self.c0 + j)

    def iter_values(self) -> Iterator[Scalar]:
        env, s = self.env, self.sheet
        for r in range(self.r0, self.r1 + 1):
            for c in range(self.c0, self.c1 + 1):
                yield env.cell(s, r, c)

    def to_rows(self) -> list[list[Scalar]]:
        env, s = self.env, self.sheet
        return [[env.cell(s, r, c) for c in range(self.c0, self.c1 + 1)] for r in range(self.r0, self.r1 + 1)]


Matrix = Arr | RangeVal


def is_matrix(v: Any) -> bool:
    return isinstance(v, (Arr, RangeVal))


# -- number <-> text -------------------------------------------------------------------------------
_NUM_TEXT = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_NUM_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?$")


def parse_number(s: str) -> float | None:
    """Text to number the way Excel coerces it in arithmetic (plain, thousands, percent)."""
    t = s.strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):  # accounting negative: (100)
        t, neg = t[1:-1].strip(), True
    if t[:1] in "$" or t[:2] in ("-$", "+$"):
        t = t.replace("$", "", 1)
    pct = t.endswith("%")
    if pct:
        t = t[:-1].strip()
    if _NUM_TEXT.match(t):
        v = float(t)
    elif _NUM_THOUSANDS.match(t):
        v = float(t.replace(",", ""))
    else:
        return None
    if math.isinf(v) or math.isnan(v):
        return None
    v = v / 100 if pct else v
    return -v if neg else v


def num_to_text(v: float) -> str:
    """General number format: up to 15 significant digits, Excel-style exponent."""
    if v == 0:
        return "0"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = f"{v:.15g}"
    if "e" in s:
        mant, exp = s.split("e")
        sign = exp[0]
        digits = exp[1:].lstrip("0") or "0"
        if len(digits) < 2:
            digits = "0" + digits
        return f"{mant}E{sign}{digits}"
    return s


# -- coercion (all raise XlRaise) -------------------------------------------------------------------
def check(v: Scalar) -> Scalar:
    if isinstance(v, XlError):
        raise XlRaise(v)
    return v


def to_num(v: Scalar) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    if isinstance(v, str):
        n = parse_number(v)
        if n is None:
            raise XlRaise(E.VALUE)
        return n
    if isinstance(v, XlError):
        raise XlRaise(v)
    raise XlRaise(E.VALUE)


def to_str(v: Scalar) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return num_to_text(float(v))
    if isinstance(v, XlError):
        raise XlRaise(v)
    raise XlRaise(E.VALUE)


def to_bool(v: Scalar) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        u = v.strip().upper()
        if u == "TRUE":
            return True
        if u == "FALSE":
            return False
        raise XlRaise(E.VALUE)
    if isinstance(v, XlError):
        raise XlRaise(v)
    raise XlRaise(E.VALUE)


def to_int(v: Scalar) -> int:
    """Number truncated toward zero (Excel's argument truncation)."""
    n = to_num(v)
    return int(n)


# -- comparison ---------------------------------------------------------------------------------------
def _rank(v: Scalar) -> int:
    if isinstance(v, bool):
        return 2
    if isinstance(v, str):
        return 1
    return 0


def compare(a: Scalar, b: Scalar) -> int:
    """Excel ordering: numbers < text < booleans; text case-insensitive; empty adapts to the other."""
    if a is None and b is None:
        return 0
    if a is None:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0.0)
    if b is None:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0.0)
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 1:
        x, y = a.lower(), b.lower()  # type: ignore[union-attr]
    else:
        x, y = float(a), float(b)
    return -1 if x < y else (1 if x > y else 0)


def eq_values(a: Scalar, b: Scalar) -> bool:
    return compare(a, b) == 0


def finite(v: float) -> float:
    if math.isnan(v) or math.isinf(v):
        raise XlRaise(E.NUM)
    return v
