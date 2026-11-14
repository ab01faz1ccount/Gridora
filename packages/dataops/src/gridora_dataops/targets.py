"""Target adapters: turn a sheet range into a Polars frame and write results back.

Sheet data is reached ONLY through ExecContext (contract v0.2). Values are written back as values;
formulas are never produced here. M0 supports sheet ranges; data tables arrive with the TableStore (M2).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

import polars as pl
from gridora_contracts.models import (
    BoolValue,
    Cell,
    CellValue,
    DateValue,
    Delta,
    NumValue,
    Range,
    StrValue,
)
from gridora_contracts.protocols import ExecContext

from .errors import DataOpsError, pointer


@dataclass
class SheetFrame:
    frame: pl.DataFrame
    rng: Range
    has_header: bool
    names: list[str]
    formula_cells: int
    error_cells: int


def _header_name(cell: Cell | None, index: int) -> str:
    v = cell.v if cell is not None else None
    if isinstance(v, StrValue) and v.s.strip():
        return v.s.strip()
    if isinstance(v, NumValue):
        return str(int(v.n)) if float(v.n).is_integer() else str(v.n)
    if isinstance(v, BoolValue):
        return "TRUE" if v.b else "FALSE"
    return f"column_{index + 1}"  # i18n key family `columns.unnamed`; stable fallback


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


def _native(cell: Cell | None) -> tuple[str, Any]:
    v = None if cell is None else cell.v
    if v is None:
        return "null", None
    if isinstance(v, NumValue):
        return "num", float(v.n)
    if isinstance(v, StrValue):
        return "str", v.s
    if isinstance(v, BoolValue):
        return "bool", v.b
    if isinstance(v, DateValue):
        if len(v.iso) == 10:
            return "date", dt.date.fromisoformat(v.iso)
        return "datetime", dt.datetime.fromisoformat(v.iso)
    return "err", None


_DTYPES: dict[str, Any] = {
    "num": pl.Float64, "str": pl.String, "bool": pl.Boolean, "date": pl.Date, "datetime": pl.Datetime("us"),
}


def load_sheet_frame(ctx: ExecContext, rng: Range, has_header: bool, *, allow_formulas: bool) -> SheetFrame:
    grid = ctx.read_range(rng)
    nrows, ncols = rng.r1 - rng.r0 + 1, rng.c1 - rng.c0 + 1
    grid = [(list(r) + [None] * ncols)[:ncols] for r in grid][:nrows]
    grid += [[None] * ncols for _ in range(nrows - len(grid))]

    formulas = sum(1 for row in grid for c in row if c is not None and c.f is not None)
    if formulas and not allow_formulas:
        raise DataOpsError("range_has_formulas", "the range contains formulas; this operation would turn them into values",
                           path=pointer("target"))
    body = grid[1:] if has_header else grid
    names = _dedupe([_header_name(c, i) for i, c in enumerate(grid[0])]) if has_header and grid else \
        [f"column_{i + 1}" for i in range(ncols)]

    errors = 0
    data: dict[str, pl.Series] = {}
    for j, name in enumerate(names):
        kinds = set()
        values = []
        for row in body:
            kind, val = _native(row[j])
            if kind == "err":
                errors += 1
            elif kind != "null":
                kinds.add(kind)
            values.append(val)
        if len(kinds) > 1:
            raise DataOpsError("mixed_column_types", f"column '{name}' mixes {sorted(kinds)}",
                               path=pointer("target"), hint="v1 limitation: convert the column to one type first")
        dtype = _DTYPES[next(iter(kinds))] if kinds else pl.String
        data[name] = pl.Series(name, values, dtype=dtype)
    if errors:
        raise DataOpsError("range_has_error_values", "the range contains error values (#N/A, ...)", path=pointer("target"))
    frame = pl.DataFrame(data) if data else pl.DataFrame()
    return SheetFrame(frame, rng, has_header, names, formulas, errors)


def _to_cell_value(x: Any) -> CellValue | None:
    if x is None:
        return None
    if isinstance(x, bool):
        return BoolValue(b=x)
    if isinstance(x, (int, float)):
        f = float(x)
        return None if math.isnan(f) else NumValue(n=f)  # NaN -> empty
    if isinstance(x, dt.datetime):
        return DateValue(iso=x.isoformat())
    if isinstance(x, dt.date):
        return DateValue(iso=x.isoformat())
    return StrValue(s=str(x))


def to_cell_rows(frame: pl.DataFrame, header: list[str] | None) -> list[list[CellValue | None]]:
    rows: list[list[CellValue | None]] = []
    if header is not None:
        rows.append([StrValue(s=n) for n in header])
    rows.extend([[_to_cell_value(x) for x in r] for r in frame.iter_rows()])
    return rows


def commit_sheet_frame(ctx: ExecContext, sf: SheetFrame, result: pl.DataFrame, *, max_cells: int) -> tuple[Delta, int]:
    """Write `result` over the source range with ONE write_range call (one delta). Returns (delta, cells)."""
    rows = to_cell_rows(result, list(result.columns) if sf.has_header else None)
    width = result.width
    out_rows = len(rows)
    r = sf.rng
    full = Range(sheet_id=r.sheet_id, r0=r.r0, c0=r.c0, r1=max(r.r1, r.r0 + out_rows - 1),
                 c1=max(r.c1, r.c0 + width - 1))
    if (full.r1 - full.r0 + 1) * (full.c1 - full.c0 + 1) > max_cells:
        raise DataOpsError("too_large_for_history",
                           f"the change covers more than {max_cells} cells", path=pointer("target"))
    if full != r:  # extra space needed: it must be empty (no silent overwrite, no row/col insertion in v1)
        existing = ctx.read_range(full)
        for i, row in enumerate(existing):
            for j, cell in enumerate(row):
                outside = not (r.r0 <= full.r0 + i <= r.r1 and r.c0 <= full.c0 + j <= r.c1)
                if outside and cell is not None and (cell.v is not None or cell.f is not None):
                    raise DataOpsError("would_overwrite", "the result needs space that contains data",
                                       path=pointer("target"))
    delta = ctx.write_range(full, rows)
    return delta, sum(len(x) for x in rows)
