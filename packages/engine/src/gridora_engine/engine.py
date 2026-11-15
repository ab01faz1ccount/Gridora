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
    CellWindow,
    CompatibilityReport,
    DateValue,
    Delta,
    Window,
    Workbook,
)
from gridora_contracts.protocols import CsvOptions, WorkbookHandle

from .compat.report import build_report
from .csvio.importer import import_csv_file
from .csvio.writer import write_csv
from .errors import EngineNotImplementedError, GridoraEngineError, bad_request
from .limits import ResourceLimits
from .model.dates import serial_to_iso
from .model.values import NUM, to_contract_value
from .model.workbook import WorkbookState
from .xlsx.importer import import_xlsx_file

_KNOWN_CONFIG = {"limits", "csv_neutralize_formulas", "csv_export_encoding"}
_EXPORT_ENCODINGS = {"utf-8-sig", "utf-8", "windows-1256"}


@dataclass
class Handle:
    """Opaque working-copy handle (satisfies contracts WorkbookHandle)."""

    id: str


class GridoraEngine:
    def __init__(self, config: Mapping[str, Any]) -> None:
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
        styles = state.styles
        xf_date = styles.xf_is_date if styles else []
        xf_fmt = styles.xf_numfmt if styles else []
        formulas = sheet.formulas
        cells = []
        for r, c, tag, val, style in sheet.store.window(
            window.row0, window.col0, window.rows, window.cols
        ):
            v = to_contract_value(tag, val, state.strings)
            fmt = None
            if style:
                if tag == NUM and style < len(xf_date) and xf_date[style]:
                    iso = serial_to_iso(val, state.date_system)
                    if iso is not None:
                        v = DateValue.model_construct(k="date", iso=iso)
                if style < len(xf_fmt) and xf_fmt[style]:
                    fmt = str(xf_fmt[style])
            text = formulas.get((r << 14) | c) if formulas else None
            cells.append(
                Cell.model_construct(
                    r=r, c=c, v=v, f=None if text is None else "=" + text,
                    s=style or None, t=fmt,
                )
            )
        return CellWindow(
            sheet_id=sheet_id, row0=window.row0, col0=window.col0,
            rows=window.rows, cols=window.cols, cells=cells,
        )

    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta:
        raise EngineNotImplementedError("apply_cell_edits")

    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None:
        raise EngineNotImplementedError("apply_delta")

    def recalculate(self, wb: WorkbookHandle) -> None:
        raise EngineNotImplementedError("recalculate")

    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport:
        raise EngineNotImplementedError("export_xlsx")

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
