"""Cross-module interfaces. Only apps/api wires these together.

Rules (docs/MODULE_BOUNDARIES.md): engine and dataops never import each other.
dataops reaches sheet data only through ExecContext, supplied by apps/api.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from .models import (
    CellEdit, CellWindow, CompatibilityReport, DataTable, Delta, Operation,
    OperationDescriptor, OperationResult, Pipeline, PreviewResult, Range, Target,
    ValidationError, Window, Workbook,
)


class WorkbookHandle(Protocol):
    """Opaque handle to an in-memory working copy owned by the engine."""

    id: str


class CsvOptions(Protocol):
    delimiter: Optional[str]
    encoding: Optional[str]  # None = detect; must handle UTF-8 (with/without BOM) and Windows-1256
    has_header: bool


@runtime_checkable
class WorkbookEngine(Protocol):
    """Implemented by packages/engine (Agent 1)."""

    def import_xlsx(self, path: Path) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]: ...
    def import_csv(self, path: Path, options: CsvOptions) -> tuple[WorkbookHandle, Workbook]: ...
    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow: ...
    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta: ...
    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None: ...
    def recalculate(self, wb: WorkbookHandle) -> None: ...
    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport: ...
    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> None: ...


class ExecContext(Protocol):
    """Bridge supplied by apps/api so dataops never imports engine."""

    def read_range(self, rng: Range) -> list[list[Any]]: ...
    def write_range(self, rng: Range, rows: list[list[Any]]) -> Delta: ...
    def table_store(self) -> "TableStore": ...
    user_id: str


@runtime_checkable
class OperationExecutor(Protocol):
    """Implemented by packages/dataops (Agent 2)."""

    def describe_all(self) -> list[OperationDescriptor]: ...
    def validate(self, op: Operation) -> list[ValidationError]: ...
    def preview(self, op: Operation, ctx: ExecContext, limit: int) -> PreviewResult: ...
    def apply(self, op: Operation, ctx: ExecContext) -> OperationResult: ...
    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]: ...


@runtime_checkable
class TableStore(Protocol):
    """Implemented by packages/dataops (Agent 2). Parquet versions are immutable."""

    def create_from_rows(self, workspace_id: str, name: str, columns: list[Any], rows: list[list[Any]]) -> DataTable: ...
    def read_page(self, table_id: str, offset: int, limit: int, sort: Optional[str] = None) -> list[list[Any]]: ...
    def sheet_range_to_table(self, ctx: ExecContext, rng: Range, header_row: bool,
                             dtype_overrides: Optional[dict[str, str]] = None, preview: bool = False) -> Any: ...
    def table_to_cells(self, table_id: str, ctx: ExecContext, anchor: Range) -> Delta: ...
    def restore_version(self, table_id: str, version: int) -> DataTable: ...
