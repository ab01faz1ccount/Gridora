"""Sheet <-> table bridge helpers."""
from __future__ import annotations

from typing import Any

import polars as pl
from gridora_contracts.models import Column, Range, Warning_
from gridora_contracts.protocols import ExecContext
from pydantic import BaseModel

from ..conversions import INT_LIMIT, convert_column
from ..errors import DataOpsError, pointer
from ..targets import load_sheet_frame
from .frames import columns_of, rows_of

PREVIEW_ROWS = 100


class TableImportPreview(BaseModel):
    """What `sheet_range_to_table(..., preview=True)` returns. Nothing is stored."""

    columns: list[Column]
    rows: list[list[Any]]
    row_count: int
    warnings: list[Warning_] = []


def infer_table_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Float columns whose values are all whole numbers within 2^53 become int64 (Excel stores every number as float)."""
    exprs = []
    for name, dtype in frame.schema.items():
        if dtype == pl.Float64:
            col = pl.col(name)
            whole = col.drop_nulls().is_finite().all() & (col.drop_nulls() == col.drop_nulls().floor()).all() \
                & (col.drop_nulls().abs() < INT_LIMIT).all()
            if frame.select(whole).item():
                exprs.append(col.cast(pl.Int64))
    return frame.with_columns(exprs) if exprs else frame


def a1(rng: Range) -> str:
    def col(c: int) -> str:
        s = ""
        c += 1
        while c:
            c, r = divmod(c - 1, 26)
            s = chr(65 + r) + s
        return s
    return f"{col(rng.c0)}{rng.r0 + 1}:{col(rng.c1)}{rng.r1 + 1}"


def import_range(ctx: ExecContext, rng: Range, header_row: bool,
                 overrides: dict[str, str] | None) -> tuple[pl.DataFrame, list[Warning_]]:
    sf = load_sheet_frame(ctx, rng, header_row, allow_formulas=True, lenient=True)
    frame = infer_table_frame(sf.frame)
    warnings = list(sf.warnings)
    for name, to in (overrides or {}).items():
        if name not in frame.columns:
            raise DataOpsError("unknown_column", f"dtype override for unknown column '{name}'",
                               path=pointer("dtype_overrides", name))
        c = convert_column(frame, name, to, on_error="null", path=pointer("dtype_overrides", name))
        frame, warnings = c.frame, warnings + c.warnings
    return frame, warnings


def preview_of(frame: pl.DataFrame, warnings: list[Warning_]) -> TableImportPreview:
    return TableImportPreview(columns=columns_of(frame), rows=rows_of(frame.head(PREVIEW_ROWS)),
                              row_count=frame.height, warnings=warnings)
