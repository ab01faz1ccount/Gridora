"""ColumnarEngine (contract 0.4.1, ADR-015): column-wise reads and writes without a pydantic
object per cell. Same value/formula semantics as get_cells / apply_cell_edits."""
from __future__ import annotations

import math
from array import array
from typing import Any

from gridora_contracts.models import (
    Cell,
    CellPatchDelta,
    ColumnarColumn,
    ColumnarRange,
    Range,
    RangeSnapshotDelta,
)
from gridora_contracts.protocols import BlobStore

from ..errors import (
    GridoraEngineError,
    bad_request,
    operation_conflict_too_large,
    validation_failed,
)
from ..limits import ResourceLimits
from .cellview import read_cell
from .dates import serial_to_iso
from .edits import Snap, apply_all, snapshot
from .snapshot import Cols, apply_arrays, decode_range, encode_arrays, encode_range, to_arrays
from .values import BOOL, ERR, ERR_CODES, NOVAL, NUM, STR
from .workbook import SheetState, WorkbookState

_ERR_INDEX = {c: i for i, c in enumerate(ERR_CODES)}


def check_range(rng: Range, limits: ResourceLimits) -> tuple[int, int]:
    """(rows, cols) of a valid range; the area is bounded by `max_cells`."""
    if rng.r1 < rng.r0 or rng.c1 < rng.c0:
        raise bad_request("range.invalid", "The range is empty or reversed.")
    if rng.r1 >= limits.max_rows or rng.c1 >= limits.max_cols:
        raise validation_failed("range.out_of_range", "The range lies outside the sheet limits.")
    rows, cols = rng.r1 - rng.r0 + 1, rng.c1 - rng.c0 + 1
    if rows * cols > limits.max_cells:
        raise validation_failed("range.too_large", "The range is larger than the allowed number of cells.")
    return rows, cols


def _formulas_in(sheet: SheetState, rng: Range) -> bool:
    r0, r1, c0, c1 = rng.r0, rng.r1, rng.c0, rng.c1
    for table in (sheet.formulas, sheet.fkind):
        for k in table:
            if r0 <= (k >> 14) <= r1 and c0 <= (k & 0x3FFF) <= c1:
                return True
    return False


def read_columnar(state: WorkbookState, sheet: SheetState, rng: Range, limits: ResourceLimits) -> ColumnarRange:
    rows, _cols = check_range(rng, limits)
    sheet.ensure(rng.r0, rng.r1 + 1)
    strings = state.strings
    styles_info = state.styles
    date_ids = {i for i, d in enumerate(styles_info.xf_is_date) if d} if styles_info else set()
    out: list[ColumnarColumn] = []
    for c in range(rng.c0, rng.c1 + 1):
        tags, vals, styles = sheet.store.column_arrays(c, rng.r0, rng.r1)
        present = set(tags)
        present.discard(0)
        present.discard(NOVAL)
        if not present:
            out.append(ColumnarColumn(kind="empty", values=[None] * rows))
        elif present == {NUM}:
            used = {s for t, s in zip(tags, styles, strict=True) if t == NUM}
            if not (used & date_ids):
                out.append(ColumnarColumn(kind="num", values=[v if t == NUM else None for t, v in zip(tags, vals, strict=True)]))
                continue
            if used <= date_ids:  # every number is shown as a date
                isos = [serial_to_iso(v, state.date_system) if t == NUM else None for t, v in zip(tags, vals, strict=True)]
                if all(i is not None for t, i in zip(tags, isos, strict=True) if t == NUM):
                    out.append(ColumnarColumn(kind="date", values=isos))
                    continue
            out.append(ColumnarColumn(kind="mixed", values=_mixed(state, tags, vals, styles, date_ids)))  # dates and numbers
        elif present == {STR}:
            get = strings.get
            out.append(ColumnarColumn(kind="str", values=[get(int(v)) if t == STR else None for t, v in zip(tags, vals, strict=True)]))
        elif present == {BOOL}:
            out.append(ColumnarColumn(kind="bool", values=[bool(v) if t == BOOL else None for t, v in zip(tags, vals, strict=True)]))
        else:
            out.append(ColumnarColumn(kind="mixed", values=_mixed(state, tags, vals, styles, date_ids)))
    return ColumnarRange(range=rng, columns=out, has_formulas=_formulas_in(sheet, rng))


def _mixed(state: WorkbookState, tags: bytearray, vals: Any, styles: Any, date_ids: set[int]) -> list[Any]:
    out: list[Any] = []
    for t, v, s in zip(tags, vals, styles, strict=True):
        if t == NUM:
            iso = serial_to_iso(v, state.date_system) if s in date_ids else None
            out.append({"k": "date", "iso": iso} if iso is not None else {"k": "num", "n": v})
        elif t == STR:
            out.append({"k": "str", "s": state.strings.get(int(v))})
        elif t == BOOL:
            out.append({"k": "bool", "b": bool(v)})
        elif t == ERR:
            out.append({"k": "err", "e": ERR_CODES[int(v)]})
        else:
            out.append(None)
    return out


def _cell_value(state: WorkbookState, kind: str, v: Any, style: int, limits: ResourceLimits) -> tuple[int, float, int]:
    """(tag, val, style) for one columnar value; raises validation_failed on bad data."""
    if v is None:
        return 0, 0.0, style
    if kind == "mixed":
        if not isinstance(v, dict) or "k" not in v:
            raise validation_failed("columnar.bad_value", "A mixed column value is not a cell value.")
        k = v["k"]
        payload = {"num": "n", "str": "s", "bool": "b", "err": "e", "date": "iso"}.get(k)
        if payload is None or payload not in v:
            raise validation_failed("columnar.bad_value", "A mixed column value is not a cell value.")
        return _cell_value(state, k, v[payload], style, limits)
    if kind == "num":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise validation_failed("edit.invalid_number", "The number is not a finite value.")
        return NUM, float(v), style
    if kind == "str":
        if not isinstance(v, str):
            raise validation_failed("columnar.bad_value", "A text column holds a non-text value.")
        if len(v) > limits.max_field_chars:
            raise validation_failed("edit.string_too_long", "The text is longer than 32,767 characters.")
        return STR, float(state.strings.intern(v)), style
    if kind == "bool":
        if not isinstance(v, bool):
            raise validation_failed("columnar.bad_value", "A boolean column holds a non-boolean value.")
        return BOOL, 1.0 if v else 0.0, style
    if kind == "err":
        if v not in _ERR_INDEX:
            raise validation_failed("columnar.bad_value", "Unknown error value.")
        return ERR, float(_ERR_INDEX[v]), style
    if kind == "date":
        from gridora_contracts.models import DateValue

        from .cellview import internal_value

        if not isinstance(v, str):
            raise validation_failed("columnar.bad_value", "A date column holds a non-text value.")
        return internal_value(state, DateValue(iso=v), style)
    raise validation_failed("columnar.bad_kind", "Unknown column kind.")


def write_columnar(
    state: WorkbookState, sheet: SheetState, rng: Range, data: ColumnarRange,
    limits: ResourceLimits, blobs: BlobStore | None = None,
) -> CellPatchDelta | RangeSnapshotDelta:
    rows, cols = check_range(rng, limits)
    if data.range != rng or len(data.columns) != cols or any(len(col.values) != rows for col in data.columns):
        raise bad_request("columnar.shape_mismatch", "The data does not match the range.")
    sheet.ensure(rng.r0, rng.r1 + 1)
    lazy = sheet.lazy
    src = getattr(lazy, "source", None)
    if lazy is not None and src is not None and (src.array_count or src.shared_count):
        lazy.materialize_all()
    for k in sheet.fkind:
        if rng.r0 <= (k >> 14) <= rng.r1 and rng.c0 <= (k & 0x3FFF) <= rng.c1:
            raise validation_failed("edit.protected_formula_cell", "A cell in the range belongs to a shared or array formula and cannot be edited yet.")
    for r0, c0, r1, c1 in sheet.array_ranges:
        if not (r1 < rng.r0 or r0 > rng.r1 or c1 < rng.c0 or c0 > rng.c1):
            raise validation_failed("edit.protected_formula_cell", "The range overlaps an array formula and cannot be edited yet.")
    # Build the new content as column arrays (validates everything before any change).
    new_cols: Cols = []
    changed_per_col: list[list[int] | None] = []
    changed_total = 0
    keep = limits.max_patch_cells
    form_rows: dict[int, set[int]] = {}
    for k in sheet.formulas:
        if rng.r0 <= (k >> 14) <= rng.r1 and rng.c0 <= (k & 0x3FFF) <= rng.c1:
            form_rows.setdefault((k & 0x3FFF) - rng.c0, set()).add((k >> 14) - rng.r0)
    for ci, col in enumerate(data.columns):
        tags, vals, styles = sheet.store.column_arrays(rng.c0 + ci, rng.r0, rng.r1)
        n_tags = bytearray(rows)
        n_vals: array[float] = array("d", bytes(8 * rows))
        n_styles: array[int] = array("H", styles)
        forms_here = form_rows.get(ci, set())
        positions: list[int] | None = []
        for ri, v in enumerate(col.values):
            tag, val, style = _cell_value(state, col.kind, v, styles[ri], limits)
            n_tags[ri] = tag
            n_vals[ri] = val
            n_styles[ri] = style
            old_tag = tags[ri]
            same = (tag, val if tag else 0.0, style) == (
                0 if old_tag == NOVAL else old_tag, vals[ri] if old_tag and old_tag != NOVAL else 0.0, styles[ri]
            )
            if not same or ri in forms_here:
                changed_total += 1
                if positions is not None:
                    positions.append(ri)
                    if changed_total > keep:
                        positions = None  # too many to list; counting continues
        new_cols.append((bytes(n_tags), n_vals, n_styles))
        changed_per_col.append(positions)
    if changed_total <= keep:
        changes: list[tuple[int, int, Snap]] = []
        for ci, positions in enumerate(changed_per_col):
            assert positions is not None
            nt, nv, ns = new_cols[ci]
            for ri in positions:
                changes.append((rng.r0 + ri, rng.c0 + ci, (nt[ri], nv[ri], ns[ri], None)))
        before: list[Cell] = [read_cell(state, sheet, r, c) for r, c, _s in changes]
        apply_all(sheet, changes)
        after = [read_cell(state, sheet, r, c) for r, c, _s in changes]
        return CellPatchDelta(sheet_id=rng.sheet_id, before=before, after=after)
    if blobs is None:
        raise operation_conflict_too_large()
    # Range snapshot (ADR-014): before and after content go to the blob store; the delta holds refs.
    before_blob = encode_range(state, sheet, rng.r0, rng.c0, rng.r1, rng.c1)
    after_blob = encode_arrays(state, rows, new_cols, [])
    try:
        before_ref = blobs.put(before_blob)
        after_ref = blobs.put(after_blob)
    except Exception:  # noqa: BLE001 - any store failure must become a typed error
        raise GridoraEngineError("internal_error", "snapshot.store_failed", "The change could not be stored.") from None
    apply_arrays(sheet, rng.r0, rng.c0, new_cols, [])
    return RangeSnapshotDelta(
        sheet_id=rng.sheet_id, range=rng, before_ref=before_ref, after_ref=after_ref, cell_count=changed_total
    )


def apply_range_snapshot(
    state: WorkbookState, sheet: SheetState, delta: RangeSnapshotDelta, inverse: bool,
    limits: ResourceLimits, blobs: BlobStore | None,
) -> None:
    rng = delta.range
    rows, cols = check_range(rng, limits)
    if blobs is None:
        raise GridoraEngineError("internal_error", "snapshot.unavailable", "The stored change is not available.")
    ref = delta.before_ref if inverse else delta.after_ref
    try:
        blob = blobs.get(ref)
    except Exception:  # noqa: BLE001 - missing or unreadable blob
        raise GridoraEngineError("internal_error", "snapshot.unavailable", "The stored change is not available.") from None
    dec = decode_range(blob, limits, rows, cols)
    sheet.ensure(rng.r0, rng.r1 + 1)
    lazy = sheet.lazy
    src = getattr(lazy, "source", None)
    if lazy is not None and src is not None and (src.array_count or src.shared_count):
        lazy.materialize_all()
    apply_arrays(sheet, rng.r0, rng.c0, to_arrays(state, dec), dec.formulas)


__all__ = ["apply_range_snapshot", "read_columnar", "snapshot", "write_columnar"]
