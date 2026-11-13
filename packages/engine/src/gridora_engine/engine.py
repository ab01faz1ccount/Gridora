"""WorkbookEngine implementation (contract v0.2.0). E0: skeleton only.

Handles are NOT thread-safe; apps/api serializes access per document.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gridora_contracts.models import (
    CellEdit,
    CellWindow,
    CompatibilityReport,
    Delta,
    Window,
    Workbook,
)
from gridora_contracts.protocols import CsvOptions, WorkbookHandle

from .errors import EngineNotImplementedError, bad_request
from .limits import ResourceLimits

_KNOWN_CONFIG = {"limits", "csv_neutralize_formulas", "csv_export_encoding"}
_EXPORT_ENCODINGS = {"utf-8-sig", "utf-8", "windows-1256"}


@dataclass(frozen=True)
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
        self._open: dict[str, Any] = {}

    # -- registry ---------------------------------------------------------------------------
    def _new_handle(self, state: Any) -> Handle:
        h = Handle(id=str(uuid.uuid4()))
        self._open[h.id] = state
        return h

    def _state(self, wb: WorkbookHandle) -> Any:
        try:
            return self._open[wb.id]
        except KeyError:
            raise bad_request(
                "handle.unknown", "The workbook handle is unknown or already closed."
            ) from None

    def close(self, wb: WorkbookHandle) -> None:
        """Release the working copy. Closing an unknown or closed handle is a no-op."""
        self._open.pop(wb.id, None)

    # -- contract methods not implemented yet (PLAN.md §15) -----------------------------------
    def import_xlsx(
        self, path: Path, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]:
        raise EngineNotImplementedError("import_xlsx")

    def import_csv(
        self, path: Path, options: CsvOptions, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook]:
        raise EngineNotImplementedError("import_csv")

    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow:
        raise EngineNotImplementedError("get_cells")

    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta:
        raise EngineNotImplementedError("apply_cell_edits")

    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None:
        raise EngineNotImplementedError("apply_delta")

    def recalculate(self, wb: WorkbookHandle) -> None:
        raise EngineNotImplementedError("recalculate")

    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport:
        raise EngineNotImplementedError("export_xlsx")

    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> None:
        raise EngineNotImplementedError("export_csv")
