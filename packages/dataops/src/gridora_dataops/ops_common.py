"""Helpers shared by operations."""
from __future__ import annotations

import polars as pl


def is_text(dtype: pl.DataType) -> bool:
    return dtype == pl.String


def is_numeric(dtype: pl.DataType) -> bool:
    return dtype.is_numeric()


def is_temporal(dtype: pl.DataType) -> bool:
    return dtype.is_temporal()
