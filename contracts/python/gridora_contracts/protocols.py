"""Cross-module interfaces (contract v0.2). Only apps/api wires these together.

Rules (docs/MODULE_BOUNDARIES.md): engine and dataops never import each other.
dataops reaches sheet data only through ExecContext, supplied by apps/api.

Real-module entry points (modules MUST export exactly these; apps/api imports nothing else):
    gridora_engine.create_engine(config: Mapping[str, Any]) -> WorkbookEngine
    gridora_dataops.create_executor(config: Mapping[str, Any]) -> OperationExecutor
    gridora_dataops.create_table_store(path_for: PathResolver) -> TableStore
    gridora_dataops.catalog(locale: str) -> dict[str, str]     # flat i18n key -> text
Stub implementations in apps/api expose the same factories.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from .models import (
    Cell, CellEdit, CellValue, CellWindow, ChartData, ChartSpec, CompatibilityReport, DataTable,
    Delta, Operation, OperationDescriptor, OperationResult, Pipeline, PreviewResult, Range,
    SheetLayout, StyleInfo, Target, Tool, ValidationError, Window, Workbook,
)

# path_for(owner_id, table_id, version) -> absolute path chosen by apps/api (owner of storage layout).
# Modules write/read bytes there; they never invent paths and never return them.
PathResolver = Callable[[str, str, int], Path]


class WorkbookHandle(Protocol):
    """Opaque handle to an in-memory working copy owned by the engine.
    Not thread-safe; apps/api serializes access per document. Release with WorkbookEngine.close."""

    id: str


class CsvOptions(Protocol):
    delimiter: Optional[str]
    encoding: Optional[str]  # None = detect; must handle UTF-8 (with/without BOM) and Windows-1256
    has_header: bool
    infer_types: bool


@runtime_checkable
class WorkbookEngine(Protocol):
    """Implemented by packages/engine (Agent 1).

    Delta semantics (normative): the Delta returned by apply_cell_edits contains before/after for
    the edited cells AND every recalculated dependent. It is simultaneously the undo record and the
    "changed cells" payload for the browser. apply_delta restores/re-applies cell contents exactly
    as recorded and does NOT recalculate.
    """

    def import_xlsx(self, path: Path, *, file_id: Optional[str] = None
                    ) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]: ...
    def import_csv(self, path: Path, options: CsvOptions, *, file_id: Optional[str] = None
                   ) -> tuple[WorkbookHandle, Workbook]: ...  # report attached to Workbook.compat
    def close(self, wb: WorkbookHandle) -> None: ...
    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow: ...
    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta: ...
    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None: ...
    def recalculate(self, wb: WorkbookHandle) -> None: ...
    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport: ...
    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> None: ...


@runtime_checkable
class FormattingEngine(Protocol):
    """Optional engine extension (needed before the grid can look like a spreadsheet; after slice 3).
    apps/api checks isinstance(engine, FormattingEngine) and degrades gracefully otherwise."""

    def get_styles(self, wb: WorkbookHandle, ids: list[int]) -> list[StyleInfo]: ...
    def get_sheet_layout(self, wb: WorkbookHandle, sheet_id: str) -> SheetLayout: ...


@runtime_checkable
class StructureEngine(Protocol):
    """Optional engine extension, scheduled AFTER formula work (row/col insert/delete rewrites
    references: the riskiest feature). `change` shape is defined by Agent 1 in engine docs and
    reviewed by Agent 0 before implementation. Returns a SheetStructureDelta."""

    def apply_structure_change(self, wb: WorkbookHandle, change: dict[str, Any]) -> Delta: ...


class ExecContext(Protocol):
    """Bridge supplied by apps/api so dataops never imports engine."""

    user_id: str
    workspace_id: str

    def read_range(self, rng: Range) -> list[list[Optional[Cell]]]:
        """Typed cells: formulas (Cell.f), error values and number-format hints stay visible.
        Empty cells are None."""
        ...

    def write_range(self, rng: Range, rows: list[list[Optional[CellValue]]]) -> Delta:
        """Writes VALUES (never formulas). None clears the cell. Cells of `rng` not covered by
        `rows` are cleared, so shrinking results (filter/dedupe) are a single call and a single
        cell_patch delta. Returns the engine-built delta (undo record)."""
        ...

    def table_store(self) -> "TableStore": ...


@runtime_checkable
class OperationExecutor(Protocol):
    """Implemented by packages/dataops (Agent 2)."""

    def describe_all(self) -> list[OperationDescriptor]: ...
    def validate(self, op: Operation, ctx: Optional[ExecContext] = None) -> list[ValidationError]:
        """Static validation without ctx; data-dependent checks (columns exist, types) when ctx given."""
        ...
    def preview(self, op: Operation, ctx: ExecContext, limit: int) -> PreviewResult: ...
    def apply(self, op: Operation, ctx: ExecContext) -> OperationResult: ...
    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]:
        """All-or-nothing. One OperationResult (own delta) per step; undo is per step."""
        ...
    def chart_data(self, spec: ChartSpec, ctx: ExecContext) -> ChartData: ...
    def validate_tool(self, tool: Tool, target: Target, ctx: Optional[ExecContext] = None
                      ) -> list[ValidationError]: ...
    def bind_tool(self, tool: Tool, inputs: dict[str, Any]) -> Pipeline:
        """Replaces {"$input": name} placeholders in step params with the bound values."""
        ...


@runtime_checkable
class TableStore(Protocol):
    """Implemented by packages/dataops (Agent 2). Parquet versions are immutable.
    Postgres (apps/api) owns metadata and the 'current version' pointer."""

    def create_from_rows(self, ctx: ExecContext, name: str, columns: list[Any],
                         rows: list[list[Any]]) -> DataTable: ...
    def read_page(self, table_id: str, offset: int, limit: int, sort: Optional[str] = None,
                  version: Optional[int] = None) -> list[list[Any]]: ...
    def sheet_range_to_table(self, ctx: ExecContext, rng: Range, header_row: bool,
                             dtype_overrides: Optional[dict[str, str]] = None,
                             preview: bool = False) -> Any: ...
    def table_to_cells(self, table_id: str, ctx: ExecContext, anchor: Range,
                       version: Optional[int] = None) -> Delta: ...
    def restore_version(self, table_id: str, version: int) -> DataTable:
        """Pointer swap: returns the existing DataTable at `version`; creates nothing.
        Raises version_unavailable if the version was compacted away."""
        ...
