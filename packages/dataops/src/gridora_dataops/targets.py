"""Target adapters: turn a sheet range into a Polars frame and write results back.

Sheet data is reached ONLY through ExecContext. Two paths with identical results:
  * row-major (`read_range` / `write_range`, one pydantic Cell per cell): always works, handles formulas;
  * columnar (optional `ColumnarExecContext`, contract v0.4.0): plain column lists, used when the range has no
    formulas; `mixed` columns stay exact. The columnar write skips an unchanged header row.
Values are written back as values; formulas are never produced here.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import polars as pl
from gridora_contracts.models import (
    BoolValue,
    Cell,
    CellValue,
    ColumnarColumn,
    ColumnarRange,
    DateValue,
    Delta,
    NumValue,
    Range,
    StrValue,
    Warning_,
)
from gridora_contracts.protocols import ColumnarExecContext, ExecContext
from pydantic import TypeAdapter

from .errors import DataOpsError, pointer

_CELLVALUE: TypeAdapter[Optional[CellValue]] = TypeAdapter(Optional[CellValue])


@dataclass
class SheetFrame:
    frame: pl.DataFrame
    rng: Range
    has_header: bool
    names: list[str]
    formula_cells: int
    error_cells: int
    warnings: list[Warning_] = field(default_factory=list)
    header_exact: bool = False  # every original header cell was exactly StrValue(name): rewriting it changes nothing
    columnar: bool = False      # this frame was read through the columnar path


def _header_name_v(v: CellValue | None, index: int) -> str:
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


def _native_value(v: CellValue | None) -> tuple[str, Any]:
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


def _native(cell: Cell | None) -> tuple[str, Any]:
    return _native_value(None if cell is None else cell.v)


_DTYPES: dict[str, Any] = {
    "num": pl.Float64, "str": pl.String, "bool": pl.Boolean, "date": pl.Date, "datetime": pl.Datetime("us"),
}


def _as_text(kind: str, val: Any) -> str | None:
    if val is None:
        return None
    if kind == "num":
        return str(int(val)) if float(val).is_integer() else repr(float(val))
    if kind == "bool":
        return "true" if val else "false"
    if kind in ("date", "datetime"):
        return str(val.isoformat())
    return str(val)


@dataclass
class _Col:
    """One column's native values, however they were read (shared by both paths so they cannot diverge)."""

    kinds: set[str]
    values: list[Any]
    per_row: list[str] | None  # kind of every row; only needed to turn a mixed column into text
    errors: int = 0


def _assemble(names: list[str], cols: list[_Col], *, lenient: bool, formulas: int, rng: Range, has_header: bool,
              header_exact: bool, columnar: bool) -> SheetFrame:
    errors = sum(c.errors for c in cols)
    warnings: list[Warning_] = []
    data: dict[str, pl.Series] = {}
    for name, col in zip(names, cols, strict=True):
        kinds, values = col.kinds, col.values
        if len(kinds) > 1 and lenient:
            assert col.per_row is not None
            values = [_as_text(k, v) for k, v in zip(col.per_row, values, strict=True)]
            warnings.append(Warning_(code="mixed_column_types", severity="warn", location=name,
                                     message=f"column '{name}' mixes {sorted(kinds)}; imported as text"))
            kinds = {"str"}
        if len(kinds) > 1:
            raise DataOpsError("mixed_column_types", f"column '{name}' mixes {sorted(kinds)}",
                               path=pointer("target"), hint="v1 limitation: convert the column to one type first")
        dtype = _DTYPES[next(iter(kinds))] if kinds else pl.String
        data[name] = pl.Series(name, values, dtype=dtype)
    if errors and lenient:
        warnings.append(Warning_(code="error_values_dropped", severity="warn",
                                 message=f"{errors} error value(s) (#N/A, ...) were imported as empty cells"))
    elif errors:
        raise DataOpsError("range_has_error_values", "the range contains error values (#N/A, ...)", path=pointer("target"))
    if formulas and lenient:
        warnings.append(Warning_(code="range_has_formulas", severity="info",
                                 message=f"{formulas} formula cell(s): their current values were imported"))
    frame = pl.DataFrame(data) if data else pl.DataFrame()
    return SheetFrame(frame, rng, has_header, names, formulas, errors, warnings, header_exact, columnar)


# ----------------------------------------------------------------------------------------------- reading
def _load_rows(ctx: ExecContext, rng: Range, has_header: bool, *, allow_formulas: bool, lenient: bool) -> SheetFrame:
    grid = ctx.read_range(rng)
    nrows, ncols = rng.r1 - rng.r0 + 1, rng.c1 - rng.c0 + 1
    grid = [(list(r) + [None] * ncols)[:ncols] for r in grid][:nrows]
    grid += [[None] * ncols for _ in range(nrows - len(grid))]

    formulas = sum(1 for row in grid for c in row if c is not None and c.f is not None)
    if formulas and not allow_formulas:
        raise DataOpsError("range_has_formulas", "the range contains formulas; this operation would turn them into values",
                           path=pointer("target"))
    body = grid[1:] if has_header else grid
    header_exact = False
    if has_header and grid:
        hv = [None if c is None else c.v for c in grid[0]]
        names = _dedupe([_header_name_v(v, i) for i, v in enumerate(hv)])
        header_exact = all(isinstance(v, StrValue) and v.s == n for v, n in zip(hv, names, strict=True))
    else:
        names = [f"column_{i + 1}" for i in range(ncols)]
    cols = []
    for j in range(len(names)):
        kinds: set[str] = set()
        values: list[Any] = []
        per_row: list[str] = []
        errors = 0
        for row in body:
            kind, val = _native(row[j])
            per_row.append(kind)
            if kind == "err":
                errors += 1
            elif kind != "null":
                kinds.add(kind)
            values.append(val)
        cols.append(_Col(kinds, values, per_row, errors))
    return _assemble(names, cols, lenient=lenient, formulas=formulas, rng=rng, has_header=has_header,
                     header_exact=header_exact, columnar=False)


def _value_at(col: ColumnarColumn, i: int) -> CellValue | None:
    v = col.values[i]
    if v is None:
        return None
    if col.kind == "num":
        return NumValue(n=float(v))
    if col.kind == "str":
        return StrValue(s=str(v))
    if col.kind == "bool":
        return BoolValue(b=bool(v))
    if col.kind == "date":
        return DateValue(iso=str(v))
    return _CELLVALUE.validate_python(v)  # "mixed": exact CellValue dicts


def _col_from_columnar(c: ColumnarColumn, n: int) -> _Col | None:
    vals = c.values
    if len(vals) != n:
        return None
    if c.kind == "empty":
        return _Col(set(), [None] * n, None)
    if c.kind in ("num", "str", "bool"):
        return _Col({c.kind} if vals.count(None) != n else set(), vals, None)
    if c.kind == "date":
        out: list[Any] = []
        per_row: list[str] = []
        kinds: set[str] = set()
        for v in vals:
            if v is None:
                out.append(None)
                per_row.append("null")
                continue
            k, parsed = _native_value(DateValue(iso=str(v)))
            out.append(parsed)
            per_row.append(k)
            kinds.add(k)
        return _Col(kinds, out, per_row)
    kinds = set()
    out = []
    per_row = []
    errors = 0
    for v in vals:
        k, parsed = _native_value(_CELLVALUE.validate_python(v))
        per_row.append(k)
        out.append(parsed)
        if k == "err":
            errors += 1
        elif k != "null":
            kinds.add(k)
    return _Col(kinds, out, per_row, errors)


def _load_columnar(ctx: ColumnarExecContext, rng: Range, has_header: bool, lenient: bool) -> SheetFrame | None:
    """None means 'use the row-major path' (formulas present, or the context returned a malformed range)."""
    nrows, ncols = rng.r1 - rng.r0 + 1, rng.c1 - rng.c0 + 1
    header_exact = False
    if has_header:
        hd = ctx.read_range_columnar(Range(sheet_id=rng.sheet_id, r0=rng.r0, c0=rng.c0, r1=rng.r0, c1=rng.c1))
        if hd.has_formulas or len(hd.columns) != ncols or any(len(c.values) != 1 for c in hd.columns):
            return None
        hv = [_value_at(c, 0) for c in hd.columns]
        names = _dedupe([_header_name_v(v, i) for i, v in enumerate(hv)])
        header_exact = all(isinstance(v, StrValue) and v.s == n for v, n in zip(hv, names, strict=True))
    else:
        names = [f"column_{i + 1}" for i in range(ncols)]
    nbody = nrows - (1 if has_header else 0)
    if nbody > 0:
        body = Range(sheet_id=rng.sheet_id, r0=rng.r0 + (1 if has_header else 0), c0=rng.c0, r1=rng.r1, c1=rng.c1)
        bd = ctx.read_range_columnar(body)
        if bd.has_formulas or len(bd.columns) != ncols:
            return None
        cols_in: list[ColumnarColumn] = bd.columns
    else:
        cols_in = [ColumnarColumn(kind="empty", values=[]) for _ in range(ncols)]
    cols = [_col_from_columnar(c, nbody) for c in cols_in]
    if any(c is None for c in cols):
        return None
    return _assemble(names, [c for c in cols if c is not None], lenient=lenient, formulas=0, rng=rng,
                     has_header=has_header, header_exact=header_exact, columnar=True)


def load_sheet_frame(ctx: ExecContext, rng: Range, has_header: bool, *, allow_formulas: bool,
                     lenient: bool = False, columnar: bool = True) -> SheetFrame:
    """`lenient` (bridge imports only): mixed-type columns become text and error values become empty, with warnings.
    `columnar=False` forces the row-major path (used to measure and to test both paths)."""
    if columnar and isinstance(ctx, ColumnarExecContext):
        sf = _load_columnar(ctx, rng, has_header, lenient)
        if sf is not None:
            return sf
    return _load_rows(ctx, rng, has_header, allow_formulas=allow_formulas, lenient=lenient)


# ----------------------------------------------------------------------------------------------- writing
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


def _columnar_column(s: pl.Series, length: int) -> ColumnarColumn | None:
    """A result column as a typed columnar column padded with empties to `length` (None = no pure kind: use rows)."""
    dtype = s.dtype
    pad = [None] * (length - s.len())
    if dtype.is_integer() or dtype.is_float():
        f = s.cast(pl.Float64)
        vals = f.fill_nan(None).to_list() if dtype.is_float() else f.to_list()
        kind = "num"
    elif dtype == pl.String:
        vals, kind = s.to_list(), "str"
    elif dtype == pl.Boolean:
        vals, kind = s.to_list(), "bool"
    elif dtype == pl.Date or isinstance(dtype, pl.Datetime):
        vals, kind = [None if v is None else v.isoformat() for v in s.to_list()], "date"
    else:
        return None
    vals += pad
    return ColumnarColumn(kind="empty" if vals.count(None) == len(vals) else kind, values=vals)


def _strip_is_empty(ctx: ExecContext, r: Range, columnar: bool) -> bool:
    if columnar and isinstance(ctx, ColumnarExecContext):
        cr = ctx.read_range_columnar(r)
        return not cr.has_formulas and all(c.kind == "empty" or c.values.count(None) == len(c.values) for c in cr.columns)
    return all(cell is None or (cell.v is None and cell.f is None) for row in ctx.read_range(r) for cell in row)


def check_write(ctx: ExecContext, rng: Range, out_rows: int, width: int, *, max_cells: int, columnar: bool = True) -> Range:
    """Where a result of `out_rows` x `width` cells would be written (starting at the range's top-left), after
    checking the cell cap and that any space beyond the original range is empty. Reads only; never writes.
    Only the strips OUTSIDE the original range are read."""
    full = Range(sheet_id=rng.sheet_id, r0=rng.r0, c0=rng.c0, r1=max(rng.r1, rng.r0 + out_rows - 1),
                 c1=max(rng.c1, rng.c0 + width - 1))
    if (full.r1 - full.r0 + 1) * (full.c1 - full.c0 + 1) > max_cells:
        raise DataOpsError("too_large_for_history",
                           f"the change covers more than {max_cells} cells", path=pointer("target"))
    strips = []
    if full.c1 > rng.c1:  # right of the range, all rows of `full`
        strips.append(Range(sheet_id=rng.sheet_id, r0=full.r0, c0=rng.c1 + 1, r1=full.r1, c1=full.c1))
    if full.r1 > rng.r1:  # below the range, only the columns of the range
        strips.append(Range(sheet_id=rng.sheet_id, r0=rng.r1 + 1, c0=full.c0, r1=full.r1, c1=rng.c1))
    for strip in strips:  # no silent overwrite, no row/column insertion in v1
        if not _strip_is_empty(ctx, strip, columnar):
            raise DataOpsError("would_overwrite", "the result needs space that contains data", path=pointer("target"))
    return full


def commit_sheet_frame(ctx: ExecContext, sf: SheetFrame, result: pl.DataFrame, *, max_cells: int,
                       columnar: bool = True) -> tuple[Delta, int]:
    """Write `result` over the source range with ONE write call (one delta). Returns (delta, cells written).

    Columnar fast path (optional context, header unchanged or absent, every column has a pure kind): only the body is
    written, as typed columns; the header row is not touched, so it is not even converted. Everything else is the
    exact row-major write. Both leave the sheet in the same state."""
    header = list(result.columns) if sf.has_header else None
    out_rows = result.height + (1 if sf.has_header else 0)
    full = check_write(ctx, sf.rng, out_rows, result.width, max_cells=max_cells, columnar=columnar)
    if columnar and isinstance(ctx, ColumnarExecContext) and (not sf.has_header or (
            sf.header_exact and header == sf.names and full.r1 > full.r0)):
        first = full.r0 + (1 if sf.has_header else 0)
        length = full.r1 - first + 1
        cols = [_columnar_column(result[c], length) for c in result.columns]
        if all(c is not None for c in cols):
            body = Range(sheet_id=full.sheet_id, r0=first, c0=full.c0, r1=full.r1, c1=full.c1)
            filler = [ColumnarColumn(kind="empty", values=[None] * length)] * (full.c1 - full.c0 + 1 - len(cols))
            data = ColumnarRange(range=body, columns=[c for c in cols if c is not None] + filler, has_formulas=False)
            return ctx.write_range_columnar(body, data), result.height * result.width
    rows = to_cell_rows(result, header)
    delta = ctx.write_range(full, rows)
    return delta, result.height * result.width  # data cells in the result (the header row is not counted)
