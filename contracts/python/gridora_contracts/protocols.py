"""Cross-module interfaces (contract v0.2). Only apps/api wires these together.

Rules (docs/MODULE_BOUNDARIES.md): engine and dataops never import each other.
dataops reaches sheet data only through ExecContext, supplied by apps/api.

Real-module entry points (modules MUST export exactly these; apps/api imports nothing else):
    gridora_engine.create_engine(config: Mapping[str, Any], blobs: Optional[BlobStore] = None) -> WorkbookEngine
    gridora_dataops.create_executor(config: Mapping[str, Any]) -> OperationExecutor
    gridora_dataops.create_table_store(path_for: PathResolver) -> TableStore
    gridora_dataops.catalog(locale: str) -> dict[str, str]     # flat i18n key -> text
Stub implementations in apps/api expose the same factories.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from .models import (
    Cell, CellEdit, CellValue, CellWindow, ChartData, ColumnarRange, ChartSpec, CompatibilityReport, DataTable,
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
    """Implemented by packages/engine.

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
    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> CompatibilityReport:
        """v0.3.0 (CC-9): returns an export report so neutralized or unencodable cells are never silent."""
        ...


@runtime_checkable
class FindFillEngine(Protocol):
    """Optional engine extension (v0.7.0). apps/api feature-detects it with isinstance()."""

    def find_cells(self, wb: WorkbookHandle, sheet_id: str, query: str, *, match_case: bool = False,
                   whole_cell: bool = False, in_formulas: bool = False,
                   after: Optional[tuple[int, int]] = None, limit: int = 200
                   ) -> tuple[list[tuple[int, int]], bool]: ...
    def fill_edits(self, wb: WorkbookHandle, sheet_id: str, source: tuple[int, int, int, int],
                   target: tuple[int, int, int, int]) -> list[CellEdit]: ...


@runtime_checkable
class CalendarEngine(Protocol):
    """Optional engine extension (v0.6.0, ADR-016). apps/api feature-detects it with isinstance()."""

    def set_calendar(self, wb: WorkbookHandle, calendar: str) -> None:
        """Switch the calendar date functions use for this workbook and recalculate. Cell values are not
        rewritten in history; the setting is a view option that apps/api persists per workbook."""
        ...
    def detect_date_columns(self, wb: WorkbookHandle, sheet_id: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class FormattingEngine(Protocol):
    """Optional engine extension (needed before the grid can look like a spreadsheet; after slice 3).
    apps/api checks isinstance(engine, FormattingEngine) and degrades gracefully otherwise."""

    def get_styles(self, wb: WorkbookHandle, ids: list[int]) -> list[StyleInfo]: ...
    def get_sheet_layout(self, wb: WorkbookHandle, sheet_id: str) -> SheetLayout: ...


@runtime_checkable
class ColumnarEngine(Protocol):
    """Optional engine extension (v0.4.1, ADR-015; proposed by the engine module as CC-12).
    apps/api feature-detects it with isinstance(engine, ColumnarEngine) and builds
    ColumnarExecContext on top of it. Same value/formula semantics as get_cells and
    apply_cell_edits; has_formulas must be True if any cell in the range has a formula
    (shared/array children included)."""

    def read_range_columnar(self, wb: WorkbookHandle, rng: Range) -> ColumnarRange: ...
    def write_range_columnar(self, wb: WorkbookHandle, rng: Range, data: ColumnarRange) -> Delta:
        """Values only; uncovered cells of rng are cleared. Delta is a cell_patch (<= 200,000
        cells) or, once the engine implements it, a range_snapshot (blob via BlobStore)."""
        ...


@runtime_checkable
class StructureEngine(Protocol):
    """Optional engine extension, scheduled AFTER formula work (row/col insert/delete rewrites
    references: the riskiest feature). `change` shape is defined by the engine module in engine docs and
    reviewed by the maintainer before implementation. Returns a SheetStructureDelta."""

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
class ColumnarExecContext(Protocol):
    """Optional ExecContext extension (v0.4.0, ADR-014). dataops feature-detects it with
    isinstance(ctx, ColumnarExecContext) and falls back to read_range/write_range otherwise.
    Purpose: skip building a pydantic Cell per cell (about 7 microseconds per cell measured)."""

    def read_range_columnar(self, rng: Range) -> ColumnarRange: ...

    def write_range_columnar(self, rng: Range, data: ColumnarRange) -> Delta:
        """Same semantics as write_range: values only, uncovered cells of `rng` are cleared.
        The delta may be a cell_patch, or a range_snapshot once the engine supports it."""
        ...


class BlobStore(Protocol):
    """Supplied by apps/api to an engine that produces range_snapshot deltas (ADR-014).
    Refs are opaque, owner-scoped by apps/api; the engine never sees paths."""

    def put(self, data: bytes) -> str: ...
    def get(self, ref: str) -> bytes: ...


@runtime_checkable
class OperationExecutor(Protocol):
    """Implemented by packages/dataops."""

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
    """Implemented by packages/dataops. Parquet versions are immutable.
    Postgres (apps/api) owns metadata and the 'current version' pointer."""

    def create_from_rows(self, ctx: ExecContext, name: str, columns: list[Any],
                         rows: list[list[Any]]) -> DataTable: ...
    def read_page(self, table_id: str, offset: int, limit: int, sort: Optional[str] = None,
                  version: Optional[int] = None) -> list[list[Any]]: ...
    def sheet_range_to_table(self, ctx: ExecContext, rng: Range, header_row: bool,
                             dtype_overrides: Optional[dict[str, str]] = None,
                             preview: bool = False, name: Optional[str] = None) -> Any: ...  # name: v0.4.0
    def table_to_cells(self, table_id: str, ctx: ExecContext, anchor: Range,
                       version: Optional[int] = None) -> Delta: ...
    def restore_version(self, table_id: str, version: int) -> DataTable:
        """Pointer swap: returns the existing DataTable at `version`; creates nothing.
        Raises version_unavailable if the version was compacted away."""
        ...
