"""WorkbookEngine implementation (contract v0.2.0). E0: skeleton only.

Handles are NOT thread-safe; apps/api serializes access per document.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gridora_contracts.models import (
    Cell,
    CellEdit,
    CellPatchDelta,
    CellWindow,
    ColumnarRange,
    CompatibilityReport,
    Delta,
    Range,
    Window,
    Workbook,
)
from gridora_contracts.protocols import BlobStore, CsvOptions, WorkbookHandle

from .compat.report import build_report
from .csvio.importer import import_csv_file
from .csvio.writer import write_csv
from .errors import (
    EngineNotImplementedError,
    GridoraEngineError,
    bad_request,
    too_large_for_history,
    validation_failed,
)
from .limits import ResourceLimits
from .model.cellview import cell_to_internal, internal_value, make_cell, read_cell
from .model.columnar import apply_range_snapshot, read_columnar, write_columnar
from .model.edits import Snap, apply_all, key_of
from .model.workbook import SheetState, WorkbookState
from .xlsx.exporter import export_xlsx_file
from .xlsx.importer import import_xlsx_file

_KNOWN_CONFIG = {"limits", "csv_neutralize_formulas", "csv_export_encoding"}
_EXPORT_ENCODINGS = {"utf-8-sig", "utf-8", "windows-1256"}


@dataclass
class Handle:
    """Opaque working-copy handle (satisfies contracts WorkbookHandle)."""

    id: str


class GridoraEngine:
    def __init__(self, config: Mapping[str, Any], blobs: BlobStore | None = None) -> None:
        self.blobs = blobs
        unknown = set(config) - _KNOWN_CONFIG
        if unknown:
            raise bad_request("config.unknown_key", "Unknown engine configuration key.")
        self.limits = ResourceLimits.from_mapping(config.get("limits", {}))
        self.csv_neutralize_formulas: bool = bool(config.get("csv_neutralize_formulas", True))
        enc = str(config.get("csv_export_encoding", "utf-8-sig"))
        if enc not in _EXPORT_ENCODINGS:
            raise bad_request("config.bad_encoding", "Unsupported CSV export encoding.")
        self.csv_export_encoding = enc
        self._open: dict[str, WorkbookState] = {}

    # -- registry ---------------------------------------------------------------------------
    def _new_handle(self, state: WorkbookState) -> Handle:
        h = Handle(id=state.id)
        self._open[h.id] = state
        return h

    def _state(self, wb: WorkbookHandle) -> WorkbookState:
        try:
            return self._open[wb.id]
        except KeyError:
            raise bad_request(
                "handle.unknown", "The workbook handle is unknown or already closed."
            ) from None

    def close(self, wb: WorkbookHandle) -> None:
        """Release the working copy. Closing an unknown or closed handle is a no-op."""
        state = self._open.pop(wb.id, None)
        if state is not None:
            state.close()

    # -- contract methods not implemented yet (PLAN.md §15) -----------------------------------
    def import_xlsx(
        self, path: Path, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]:
        state = import_xlsx_file(path, self.limits, file_id)
        assert state.compat is not None
        return self._new_handle(state), state.to_model(), state.compat

    def import_csv(
        self, path: Path, options: CsvOptions, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook]:
        state = import_csv_file(path, options, self.limits, file_id)
        return self._new_handle(state), state.to_model()

    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow:
        state = self._state(wb)
        sheet = state.sheet(sheet_id)
        if sheet is None:
            raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
        sheet.ensure(window.row0, window.row0 + window.rows)
        cells = [
            make_cell(state, sheet, r, c, tag, val, style)
            for r, c, tag, val, style in sheet.store.window(
                window.row0, window.col0, window.rows, window.cols
            )
        ]
        return CellWindow(
            sheet_id=sheet_id, row0=window.row0, col0=window.col0,
            rows=window.rows, cols=window.cols, cells=cells,
        )

    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta:
        state, sheet = self._sheet(wb, sheet_id)
        limits = self.limits
        if len(edits) > limits.max_patch_cells:
            raise too_large_for_history()
        final: dict[int, CellEdit] = {}
        for e in edits:  # validate everything first; the last edit of a cell wins
            if e.r >= limits.max_rows or e.c >= limits.max_cols:
                raise validation_failed("edit.out_of_range", "A cell lies outside the sheet limits.")
            if e.formula is not None:
                raise validation_failed(
                    "edit.formulas_unsupported", "Formulas cannot be entered yet."
                )
            v = e.value
            if v is not None and v.k == "num" and (v.n != v.n or v.n in (float("inf"), float("-inf"))):
                raise validation_failed("edit.invalid_number", "The number is not a finite value.")
            if v is not None and v.k == "str" and len(v.s) > limits.max_field_chars:
                raise validation_failed("edit.string_too_long", "The text is longer than 32,767 characters.")
            final[key_of(e.r, e.c)] = e
        self._load_for_edit(sheet, [(k >> 14) for k in final])
        for k in final:
            if self._protected(sheet, k >> 14, k & 0x3FFF):
                raise validation_failed(
                    "edit.protected_formula_cell",
                    "This cell belongs to a shared or array formula and cannot be edited yet.",
                )
        before: list[Cell] = []
        changes: list[tuple[int, int, Snap]] = []
        for k, e in final.items():
            r, c = k >> 14, k & 0x3FFF
            before.append(read_cell(state, sheet, r, c))
            _tag, _val, style = sheet.store.get(r, c)
            tag, val, style = internal_value(state, e.value, style)
            changes.append((r, c, (tag, val, style, None)))
        apply_all(sheet, changes)
        after = [read_cell(state, sheet, r, c) for r, c, _s in changes]
        return CellPatchDelta(sheet_id=sheet_id, before=before, after=after)

    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None:
        if delta.kind == "range_snapshot":
            state, sheet = self._sheet(wb, delta.sheet_id)
            apply_range_snapshot(state, sheet, delta, inverse, self.limits, self.blobs)
            return
        if delta.kind != "cell_patch":
            raise validation_failed("delta.unsupported_kind", "This kind of change is not supported yet.")
        state, sheet = self._sheet(wb, delta.sheet_id)
        cells = delta.before if inverse else delta.after
        if len(cells) > self.limits.max_patch_cells:
            raise too_large_for_history()
        for cell in cells:
            if cell.r >= self.limits.max_rows or cell.c >= self.limits.max_cols or (cell.s or 0) > 65535:
                raise validation_failed("delta.out_of_range", "The change refers to a cell outside the sheet.")
        self._load_for_edit(sheet, [cell.r for cell in cells])
        changes: list[tuple[int, int, Snap]] = []
        for cell in cells:
            tag, val, style, text = cell_to_internal(state, cell)
            changes.append((cell.r, cell.c, (tag, val, style, text)))
        apply_all(sheet, changes)

    # -- ColumnarEngine (contract 0.4.1) ------------------------------------------------------
    def read_range_columnar(self, wb: WorkbookHandle, rng: Range) -> ColumnarRange:
        state, sheet = self._sheet(wb, rng.sheet_id)
        return read_columnar(state, sheet, rng, self.limits)

    def write_range_columnar(self, wb: WorkbookHandle, rng: Range, data: ColumnarRange) -> Delta:
        state, sheet = self._sheet(wb, rng.sheet_id)
        return write_columnar(state, sheet, rng, data, self.limits, self.blobs)

    # -- helpers ----------------------------------------------------------------------------
    def _sheet(self, wb: WorkbookHandle, sheet_id: str) -> tuple[WorkbookState, SheetState]:
        state = self._state(wb)
        sheet = state.sheet(sheet_id)
        if sheet is None:
            raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
        return state, sheet

    @staticmethod
    def _load_for_edit(sheet: SheetState, rows: list[int]) -> None:
        """Make sure every row about to change is materialized BEFORE it changes (a later lazy
        parse would overwrite edits). Sheets with shared/array formulas are loaded completely so
        the protection check sees every formula group."""
        lazy = sheet.lazy
        if lazy is None:
            return
        src = getattr(lazy, "source", None)
        if src is not None and (src.array_count or src.shared_count):
            lazy.materialize_all()
            return
        for block in sorted({r >> 8 for r in rows}):
            lazy.ensure(block << 8, (block << 8) + 1)

    @staticmethod
    def _protected(sheet: SheetState, r: int, c: int) -> bool:
        if (r << 14) | c in sheet.fkind:
            return True
        return any(r0 <= r <= r1 and c0 <= c <= c1 for r0, c0, r1, c1 in sheet.array_ranges)

    def recalculate(self, wb: WorkbookHandle) -> None:
        raise EngineNotImplementedError("recalculate")

    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport:
        return export_xlsx_file(self._state(wb), path, self.limits)

    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> CompatibilityReport:
        state = self._state(wb)
        sheet = state.sheet(sheet_id)
        if sheet is None:
            raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
        n = write_csv(
            path, sheet.store, state.strings, self.csv_export_encoding,
            self.csv_neutralize_formulas,
        )
        return build_report("export", {"csv.formula_text_neutralized": n})
