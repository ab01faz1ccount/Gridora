"""Polars frame <-> contract column schema, JSON-safe row values."""
from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal
from typing import Any

import polars as pl
from gridora_contracts.models import Column

from ..conversions import POLARS_DTYPES


def dtype_name(dtype: pl.DataType) -> str:
    if dtype.is_integer():
        return "int64"
    if dtype.is_float():
        return "float64"
    if dtype == pl.Boolean:
        return "bool"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    if isinstance(dtype, pl.Decimal):
        return "decimal"
    return "string"  # strings and anything else (all-null columns are cast to string on write)


def normalize_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Make dtypes storable: ints -> Int64, floats -> Float64, datetimes -> microseconds, other -> String."""
    exprs = []
    for name, dtype in frame.schema.items():
        want = POLARS_DTYPES[dtype_name(dtype)] if dtype_name(dtype) != "decimal" else dtype
        if dtype != want:
            exprs.append(pl.col(name).cast(want))
    return frame.with_columns(exprs) if exprs else frame


def columns_of(frame: pl.DataFrame) -> list[Column]:
    return [Column(name=n, dtype=dtype_name(t)) for n, t in frame.schema.items()]


def jsonable(x: Any) -> Any:
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, (dt.datetime, dt.date)):
        return x.isoformat()
    if isinstance(x, Decimal):
        return str(x)
    return x


def rows_of(frame: pl.DataFrame) -> list[list[Any]]:
    return [[jsonable(x) for x in r] for r in frame.iter_rows()]
