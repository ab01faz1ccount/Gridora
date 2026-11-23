from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import xlerrors as E
from ..values import Arr, RangeVal, XlRaise, to_num
from ..xlerrors import XlError
from .helpers import scalar
from .registry import fn


def _is(name: str, pred: Callable[[Any], bool]) -> Callable[..., bool]:
    @fn(name, 1, 1)
    def _f(ctx: Any, a: Any) -> bool:
        return pred(scalar(ctx, a))

    return _f


_is("ISNUMBER", lambda v: isinstance(v, (int, float)) and not isinstance(v, bool))
_is("ISTEXT", lambda v: isinstance(v, str))
_is("ISNONTEXT", lambda v: not isinstance(v, str))
_is("ISLOGICAL", lambda v: isinstance(v, bool))
_is("ISBLANK", lambda v: v is None)
_is("ISERROR", lambda v: isinstance(v, XlError))
_is("ISERR", lambda v: isinstance(v, XlError) and v != E.NA)
_is("ISNA", lambda v: v == E.NA)


@fn("ISREF", 1, 1)
def f_isref(ctx: Any, a: Any) -> bool:
    return isinstance(a, RangeVal)


@fn("ISEVEN", 1, 1)
def f_iseven(ctx: Any, a: Any) -> bool:
    return int(abs(to_num(scalar(ctx, a)))) % 2 == 0


@fn("ISODD", 1, 1)
def f_isodd(ctx: Any, a: Any) -> bool:
    return int(abs(to_num(scalar(ctx, a)))) % 2 == 1


@fn("N", 1, 1)
def f_n(ctx: Any, a: Any) -> Any:
    v = scalar(ctx, a)
    if isinstance(v, XlError):
        return v
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


@fn("T", 1, 1)
def f_t(ctx: Any, a: Any) -> Any:
    v = scalar(ctx, a)
    if isinstance(v, XlError):
        return v
    return v if isinstance(v, str) else ""


@fn("NA", 0, 0)
def f_na(ctx: Any) -> XlError:
    return E.NA


@fn("TYPE", 1, 1)
def f_type(ctx: Any, a: Any) -> float:
    if isinstance(a, Arr):
        return 64.0
    v = scalar(ctx, a)
    if isinstance(v, XlError):
        return 16.0
    if isinstance(v, bool):
        return 4.0
    if isinstance(v, str):
        return 2.0
    return 1.0


_ERR_TYPE = {"#NULL!": 1, "#DIV/0!": 2, "#VALUE!": 3, "#REF!": 4, "#NAME?": 5, "#NUM!": 6, "#N/A": 7}


@fn("ERROR.TYPE", 1, 1)
def f_error_type(ctx: Any, a: Any) -> float:
    v = scalar(ctx, a)
    if isinstance(v, XlError) and v.code in _ERR_TYPE:
        return float(_ERR_TYPE[v.code])
    raise XlRaise(E.NA)


@fn("ROW", 0, 1)
def f_row(ctx: Any, a: Any = None) -> Any:
    if a is None:
        return float(ctx.row + 1)
    if isinstance(a, RangeVal):
        if ctx.arr and a.nrows > 1:
            return Arr([[float(a.r0 + i + 1)] for i in range(a.nrows)])
        return float(a.r0 + 1)
    raise XlRaise(E.VALUE)


@fn("COLUMN", 0, 1)
def f_column(ctx: Any, a: Any = None) -> Any:
    if a is None:
        return float(ctx.col + 1)
    if isinstance(a, RangeVal):
        if ctx.arr and a.ncols > 1:
            return Arr([[float(a.c0 + j + 1) for j in range(a.ncols)]])
        return float(a.c0 + 1)
    raise XlRaise(E.VALUE)


@fn("ROWS", 1, 1, arr=True)
def f_rows(ctx: Any, a: Any) -> float:
    if isinstance(a, RangeVal):
        return float(a.nominal_rows if a.nominal_rows is not None else a.nrows)
    if isinstance(a, Arr):
        return float(a.nrows)
    if isinstance(a, XlError):
        raise XlRaise(a)
    return 1.0


@fn("COLUMNS", 1, 1, arr=True)
def f_columns(ctx: Any, a: Any) -> float:
    if isinstance(a, RangeVal):
        return float(a.nominal_cols if a.nominal_cols is not None else a.ncols)
    if isinstance(a, Arr):
        return float(a.ncols)
    if isinstance(a, XlError):
        raise XlRaise(a)
    return 1.0


@fn("SHEET", 0, 1)
def f_sheet(ctx: Any, a: Any = None) -> float:
    if a is None:
        return float(ctx.sheet + 1)
    if isinstance(a, RangeVal):
        return float(a.sheet + 1)
    raise XlRaise(E.NA)
