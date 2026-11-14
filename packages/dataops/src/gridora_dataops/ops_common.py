"""Helpers shared by operations."""
from __future__ import annotations

import datetime as dt
from typing import Any

import polars as pl

from .errors import DataOpsError, pointer


def is_text(dtype: pl.DataType) -> bool:
    return dtype == pl.String


def text_columns(frame: pl.DataFrame, columns: list[str], ptr: str = "/params/columns") -> list[str]:
    """Explicit columns must be text (error points at the entry); an empty list means 'all text columns'."""
    if not columns:
        return [c for c, t in frame.schema.items() if t == pl.String]
    for i, c in enumerate(columns):
        if frame.schema[c] != pl.String:
            raise DataOpsError("type_mismatch", f"column '{c}' is not text", path=f"{ptr}/{i}")
    return list(columns)


def unique_name(base: str, taken: list[str] | set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def coerce_scalar(value: Any, dtype: pl.DataType, ptr: str) -> Any:
    """A JSON scalar -> a Python value that fits `dtype`; errors point at `ptr`."""
    try:
        if value is None:
            raise ValueError
        if dtype.is_temporal():
            if not isinstance(value, str):
                raise ValueError
            d = dt.datetime.fromisoformat(value) if len(value) > 10 else dt.date.fromisoformat(value)
            if isinstance(dtype, pl.Datetime):
                return d if isinstance(d, dt.datetime) else dt.datetime(d.year, d.month, d.day)
            return d.date() if isinstance(d, dt.datetime) else d
        if dtype.is_numeric():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError
            return int(value) if dtype.is_integer() and float(value).is_integer() else float(value)
        if dtype == pl.Boolean and isinstance(value, bool):
            return value
        if dtype == pl.String and isinstance(value, str):
            return value
    except ValueError:
        pass
    raise DataOpsError("type_mismatch", f"value does not fit a {dtype} column", path=ptr)


__all__ = ["coerce_scalar", "is_text", "pointer", "text_columns", "unique_name"]
