"""Shared data contracts for Gridora (normative; mirrors docs/DATA_MODEL.md).

Owned by the maintainer. Other agents must not edit this file; propose changes via a
CONTRACT_CHANGE note in the PR description.

Conventions: rows/cols are 0-based ints; IDs are UUID strings; timestamps are ISO-8601 UTC.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1
CONTRACT_VERSION = "0.7.0"
MAX_WINDOW_ROWS = 1000  # decided in Phase 2 review (configurable lower by the API)
MAX_WINDOW_COLS = 100


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- cells ----
class NumValue(_Base):
    k: Literal["num"] = "num"
    n: float


class StrValue(_Base):
    k: Literal["str"] = "str"
    s: str


class BoolValue(_Base):
    k: Literal["bool"] = "bool"
    b: bool


class ErrValue(_Base):
    k: Literal["err"] = "err"
    e: Literal["#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!",
               "#SPILL!", "#CALC!", "#GETTING_DATA"]


class DateValue(_Base):
    k: Literal["date"] = "date"
    iso: str  # display convenience; engine stores serial numbers internally


CellValue = Annotated[
    Union[NumValue, StrValue, BoolValue, ErrValue, DateValue], Field(discriminator="k")
]


class Cell(_Base):
    r: int = Field(ge=0)
    c: int = Field(ge=0)
    v: Optional[CellValue] = None
    f: Optional[str] = None  # formula text, e.g. "=SUM(A1:A10)"
    s: Optional[int] = None  # style id
    t: Optional[str] = None  # number-format id/hint
    d: Optional[str] = None  # text as the number format shows it (numbers with a non-General format only)


class CellEdit(_Base):
    r: int = Field(ge=0)
    c: int = Field(ge=0)
    value: Optional[CellValue] = None
    formula: Optional[str] = None  # exactly one of value/formula, or neither to clear


class Range(_Base):
    sheet_id: str
    r0: int = Field(ge=0)
    c0: int = Field(ge=0)
    r1: int = Field(ge=0)  # inclusive
    c1: int = Field(ge=0)  # inclusive


class Window(_Base):
    row0: int = Field(ge=0)
    col0: int = Field(ge=0)
    rows: int = Field(ge=1, le=MAX_WINDOW_ROWS)
    cols: int = Field(ge=1, le=MAX_WINDOW_COLS)


class CellWindow(_Base):
    sheet_id: str
    row0: int
    col0: int
    rows: int
    cols: int
    cells: list[Cell]  # non-empty cells only


# ------------------------------------------------------------- workbook ----
class Frozen(_Base):
    rows: int = 0
    cols: int = 0


class FrozenRequest(_Base):
    rows: int = Field(ge=0, le=100)
    cols: int = Field(ge=0, le=26)


class SheetMeta(_Base):
    id: str
    name: str
    index: int
    visible: Literal["visible", "hidden", "very_hidden"] = "visible"
    row_count: int
    col_count: int
    frozen: Optional[Frozen] = None
    rtl: bool = False  # right-to-left sheet view (Persian-first UI)


class DefinedName(_Base):
    name: str
    scope: str  # "workbook" or a sheet_id
    ref: str


class CompatItem(_Base):
    code: str  # stable registry code, e.g. "xlsx.pivot_table"
    status: Literal["supported", "partial", "unsupported"]
    preserved: bool
    editable: bool
    message: str
    location: Optional[str] = None


class CompatSummary(_Base):
    supported: int = 0
    partial: int = 0
    unsupported: int = 0


class CompatibilityReport(_Base):
    source: Literal["import", "export"]
    generated_at: datetime
    items: list[CompatItem]
    summary: CompatSummary


class Workbook(_Base):
    schema_version: int = SCHEMA_VERSION
    id: str
    file_id: str
    name: str
    sheets: list[SheetMeta]
    defined_names: list[DefinedName] = []
    date_system: Literal["1900", "1904"] = "1900"
    compat: Optional[CompatibilityReport] = None
    calendar: Literal["jalali", "gregorian", "hijri"] = "jalali"  # v0.6.0 (ADR-016): how date functions read/write dates
    workspace_id: Optional[str] = None  # v0.7.0: set by the API (tables, tools and exports live in the workspace)


class DateColumn(_Base):
    """v0.6.0: a column that holds dates (real dates or date-looking text). Detection only; nothing is converted."""

    col: int
    kind: Literal["serial", "text"]
    calendar: Literal["jalali", "gregorian", "hijri"]  # calendar the text is written in; "gregorian" for serials
    header_row: bool
    dates: int
    total: int


class DateColumns(_Base):
    sheet_id: str
    columns: list[DateColumn]


class ExportRequest(_Base):
    """v0.6.1: POST /workbooks/{id}/export. csv needs sheet_id (one sheet per file)."""

    format: Literal["xlsx", "csv"]
    sheet_id: Optional[str] = None


class SetCalendarRequest(_Base):
    calendar: Literal["jalali", "gregorian", "hijri"]


# ---------------------------------------------------------- data tables ----
DType = Literal["int64", "float64", "bool", "string", "date", "datetime", "decimal"]


class Column(_Base):
    name: str
    dtype: DType
    nullable: bool = True
    display_format: Optional[str] = None


class TableSource(_Base):
    kind: Literal["sheet_range"] = "sheet_range"
    workbook_id: str
    range: Range
    link: Literal["snapshot", "refreshable"] = "snapshot"


class DataTable(_Base):
    schema_version: int = SCHEMA_VERSION
    id: str
    workspace_id: str
    name: str
    version: int = Field(ge=1)
    columns: list[Column]
    row_count: int
    source: Optional[TableSource] = None


# ----------------------------------------------------------- workspaces ----
class Workspace(_Base):
    id: str
    owner_id: str
    name: str
    created_at: datetime


class FileRecord(_Base):
    id: str
    workspace_id: str
    owner_id: str
    kind: Literal["workbook", "table", "original", "export"]  # "export": v0.6.1
    display_name: str
    size_bytes: int
    sha256: str
    created_at: datetime
    parent_id: Optional[str] = None  # version chain; originals are immutable
    # NOTE: no filesystem path field exists, by design (SECURITY_MODEL).


MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # owner decision: 100 MB


# ----------------------------------------------------------- validation ----
class ValidationError(_Base):
    code: str
    path: str  # JSON pointer relative to the ROOT of the Operation, e.g. "/params/column"
    message: str
    hint: Optional[str] = None


class Warning_(_Base):
    code: str
    severity: Literal["info", "warn"]
    message: str
    location: Optional[str] = None


class CreateTableRequest(_Base):
    """v0.6.2: POST /workspaces/{id}/tables. Small tables only (rows are capped by apps/api);
    larger data comes from a sheet range or a file."""

    name: str = Field(min_length=1, max_length=255)
    columns: list[Column] = Field(min_length=1)
    rows: list[list[Any]] = []


class FromRangeRequest(_Base):
    """v0.6.2: POST /tables/from-range. preview=true stores nothing and answers TablePreview."""

    workbook_id: str
    range: Range
    header_row: bool = True
    dtype_overrides: Optional[dict[str, str]] = None
    preview: bool = False
    name: Optional[str] = Field(default=None, max_length=255)


class ToSheetRequest(_Base):
    """v0.6.3: POST /tables/{id}/to-sheet. Writes header + rows with the top-left at (row, col);
    refuses to overwrite non-empty cells. One undoable history entry on the workbook."""

    workbook_id: str
    sheet_id: str
    row: int = Field(default=0, ge=0)
    col: int = Field(default=0, ge=0)
    base_seq: Optional[int] = None


class TablePreview(_Base):
    columns: list[Column]
    rows: list[list[Any]]
    row_count: int
    warnings: list[Warning_] = []


class TableRows(_Base):
    table_id: str
    version: int
    columns: list[Column]
    row_count: int
    offset: int
    rows: list[list[Any]]


# ----------------------------------------------------------- operations ----
class SheetRangeTarget(_Base):
    kind: Literal["sheet_range"] = "sheet_range"
    range: Range


class DataTableTarget(_Base):
    kind: Literal["data_table"] = "data_table"
    table_id: str
    # v0.4.0: apps/api fills this with the CURRENT version pointer (it changes on undo/redo).
    # None = "latest existing version" (only safe when no undo has happened).
    version: Optional[int] = Field(default=None, ge=1)


Target = Annotated[Union[SheetRangeTarget, DataTableTarget], Field(discriminator="kind")]


class Operation(_Base):
    id: Optional[str] = None
    type: str  # key in the operation registry
    schema_version: int = SCHEMA_VERSION
    target: Target
    # Additional inputs (e.g. the right-hand table of a join). The API verifies ownership of
    # every target generically; modules never look ids up in params.
    extra_targets: list[Target] = []
    params: dict[str, Any] = {}


class OperationDescriptor(_Base):
    type: str
    label: str  # Persian-first: label keys resolved via i18n catalog
    category: str
    description: str
    params_schema: dict[str, Any]  # JSON Schema; drives GUI forms
    targets: list[Literal["sheet_range", "data_table"]]
    destructive: bool
    supports_preview: bool
    # v0.7.0 (additive): how the operation fits pipelines and tools.
    extra_inputs: int = 0  # extra targets it needs (join: 1); see PipelineStep.extra_targets
    creates_table: bool = False  # the result is always a NEW data table (the source is never changed)
    sheet_output: Literal["in_place", "new_table"] = "in_place"  # on a sheet range: write back, or a new table


class SheetPatch(_Base):
    """v0.5.0 (ADR-016): cells of ANOTHER sheet changed by recalculation of cross-sheet formulas."""

    sheet_id: str
    before: list[Cell]
    after: list[Cell]


class StyleInfo(_Base):
    """Resolved formatting for one style id (Cell.s). Optional engine extension."""

    id: int
    number_format: Optional[str] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    font_color: Optional[str] = None  # "#RRGGBB"
    fill_color: Optional[str] = None  # "#RRGGBB"
    halign: Optional[Literal["left", "center", "right", "justify"]] = None
    wrap: bool = False
    base_id: Optional[int] = None  # derived formats only: the imported format this one was made from


class CellPatchDelta(_Base):
    kind: Literal["cell_patch"] = "cell_patch"
    sheet_id: str
    before: list[Cell]
    after: list[Cell]
    others: list[SheetPatch] = Field(default_factory=list)  # v0.5.0; empty unless formulas cross sheets
    # Formats made by this change (Cell.s ids it refers to), so a replay can recreate them.
    styles: list[StyleInfo] = Field(default_factory=list)


class TableVersionDelta(_Base):
    """from_version == 0 means "the table did not exist" (operation created it);
    undo then removes it from view, redo restores it. restore_version is a pointer swap."""

    kind: Literal["table_version"] = "table_version"
    table_id: str
    from_version: int = Field(ge=0)
    to_version: int = Field(ge=1)


class RangeSnapshotDelta(_Base):
    """v0.4.0 (reserved, ADR-014): a large in-place range write whose before/after contents are
    stored as opaque blobs (engine-defined, versioned, compressed columnar format) instead of
    inline cells. Lifts the 200,000-cell cell_patch cap. Produced only by engines that implement
    BlobStore-backed snapshots; consumers must treat unknown refs as opaque."""

    kind: Literal["range_snapshot"] = "range_snapshot"
    sheet_id: str
    range: Range
    before_ref: str
    after_ref: str
    cell_count: int = Field(ge=0)


class SheetStructureDelta(_Base):
    kind: Literal["sheet_structure"] = "sheet_structure"
    sheet_id: str
    change: dict[str, Any]  # shape defined by the engine module in engine docs; reviewed by the maintainer


Delta = Annotated[
    Union[CellPatchDelta, TableVersionDelta, RangeSnapshotDelta, SheetStructureDelta],
    Field(discriminator="kind")
]


class Affected(_Base):
    cells: Optional[int] = None
    rows: Optional[int] = None


class OperationResult(_Base):
    status: Literal["ok", "error"]
    affected: Affected = Affected()
    delta: Optional[Delta] = None
    warnings: list[Warning_] = []
    errors: list[ValidationError] = []
    output: Optional[Target] = None  # e.g. a pivot that creates a new table


class PreviewResult(_Base):
    columns: list[str]
    rows: list[list[Any]]  # limited sample of the would-be result
    total_rows: Optional[int] = None
    warnings: list[Warning_] = []


class PipelineStep(_Base):
    type: str
    schema_version: int = SCHEMA_VERSION
    params: dict[str, Any] = {}
    label: Optional[str] = None
    # v0.7.0: extra inputs of a multi-input operation (e.g. the right-hand table of a join), like
    # Operation.extra_targets. `extra_target_inputs` names tool inputs of kind "table" that bind_tool
    # turns into `extra_targets` at run time (a saved tool cannot know the table in advance).
    extra_targets: list[Target] = []
    extra_target_inputs: list[str] = []


class Pipeline(_Base):
    id: Optional[str] = None
    name: str
    input_kind: Literal["sheet_range", "data_table"]
    steps: list[PipelineStep]


class ToolInput(_Base):
    name: str
    kind: Literal["column", "range", "value", "table"]
    label: str
    required: bool = True


class Tool(_Base):
    id: Optional[str] = None
    owner_id: Optional[str] = None
    name: str
    description: str = ""
    pipeline: Pipeline
    inputs: list[ToolInput] = []
    created_at: Optional[datetime] = None


class ToolRunRequest(_Base):
    """v0.6.5: POST /tools/{id}/run (a job). Only sheet-range pipelines on a workbook for now;
    every step becomes its own undoable history entry."""

    workbook_id: str
    target: Target
    inputs: dict[str, Any] = {}
    base_seq: int
    confirm_destructive: bool = False


# -------------------------------------------------------------- history ----
class HistoryEntry(_Base):
    id: str
    document_id: str
    seq: int
    operation: Operation
    delta: Delta
    label: str
    created_at: datetime
    undone: bool = False


class TableChangedResult(_Base):
    """v0.6.6: result of undo/redo on a Data Table: the entry and the table at its new version."""

    history_entry: HistoryEntry
    table: DataTable


# --------------------------------------------------------------- charts ----
class ChartSeries(_Base):
    name: Optional[str] = None
    value_col: Union[str, int]
    category_col: Optional[Union[str, int]] = None
    aggregate: Optional[Literal["sum", "avg", "count", "min", "max"]] = None


class ChartOptions(_Base):
    stacked: bool = False
    legend: bool = True
    axis_titles: Optional[dict[str, str]] = None


class ChartSpec(_Base):
    schema_version: int = SCHEMA_VERSION
    id: Optional[str] = None
    document_id: str
    type: Literal["bar", "line", "pie", "scatter", "area"]
    title: Optional[str] = None
    source: Target
    series: list[ChartSeries]
    options: ChartOptions = ChartOptions()


class ChartData(_Base):
    """ECharts-independent dataset; the web app maps it to ECharts options."""

    categories: list[Union[str, float]]
    series: list[dict[str, Any]]  # {"name": str, "values": list[number|None]}


# ------------------------------------------------- columnar range (v0.4.0) ----
ColumnKind = Literal["empty", "num", "str", "bool", "date", "mixed"]


class ColumnarColumn(_Base):
    """One column of a range as plain Python values, without a pydantic object per cell.
    kind "num": float | None; "str": str | None; "bool": bool | None;
    "date": ISO-8601 date/datetime str | None; "empty": all None;
    "mixed": list of Optional[CellValue] dicts (exact fallback, includes error values)."""

    kind: ColumnKind
    values: list[Any]


class ColumnarRange(_Base):
    range: Range
    columns: list[ColumnarColumn]  # exactly (c1 - c0 + 1) columns, each (r1 - r0 + 1) long
    # True if ANY cell has a formula. Columnar access carries values only; callers that care
    # about formulas (all in-place dataops) must then use the row-major read_range instead.
    has_formulas: bool = False


# ------------------------------------------------- styles and layout ----
class SheetLayout(_Base):
    sheet_id: str
    col_widths: dict[int, float] = {}  # only non-default
    row_heights: dict[int, float] = {}
    hidden_cols: list[int] = []
    hidden_rows: list[int] = []
    merges: list[Range] = []


# ------------------------------------------------- request / response ----
class User(_Base):
    id: str
    username: str
    role: Literal["user", "admin"]


class AuthResult(_Base):
    user: User
    csrf_token: str  # returned by POST /auth/login and GET /auth/me


class FindMatch(_Base):
    r: int
    c: int


class FindResult(_Base):  # v0.7.0
    matches: list[FindMatch]
    truncated: bool = False  # there are more matches after the last one


class FormatChange(_Base):
    """What to change; a field that is not sent stays as it is, null puts the default back."""

    number_format: Optional[str] = Field(default=None, max_length=255)
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None
    strike: Optional[bool] = None
    font_name: Optional[str] = Field(default=None, max_length=64)
    font_size: Optional[float] = Field(default=None, ge=1, le=409)
    font_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    fill_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    halign: Optional[Literal["left", "center", "right", "justify"]] = None
    wrap: Optional[bool] = None


class FormatRequest(_Base):
    base_seq: Optional[int] = None
    range: Range
    change: FormatChange


class FillRequest(_Base):  # v0.7.0
    base_seq: int
    source: Range  # the cells to continue
    target: Range  # the new cells, against one side of `source`, same columns (down/up) or rows (right/left)


class StructureRequest(_Base):  # v0.8.0
    base_seq: int
    axis: Literal["row", "col"]
    op: Literal["insert", "delete"]
    at: int = Field(ge=0)  # 0-based index of the first row/column inserted before, or deleted
    count: int = Field(ge=1, le=100_000)


class CellEditRequest(_Base):
    base_seq: int  # last history seq the client has seen; mismatch -> 409 version_conflict
    edits: list[CellEdit]


class OperationRequest(_Base):
    base_seq: int
    operation: Operation
    confirm_destructive: bool = False


class SheetCells(_Base):
    sheet_id: str
    cells: list[Cell]


class CellsChangedResult(_Base):
    """Response of PATCH cells / undo / redo / operations on sheets."""

    history_entry: "HistoryEntry"
    sheet_id: str
    cells: list[Cell]  # changed cells INCLUDING recalculated dependents (== delta.after)
    others: list["SheetCells"] = Field(default_factory=list)  # v0.5.0: same, for other sheets (== delta.others[*].after)


# ------------------------------------------------------------------ api ----
class ErrorDetail(_Base):
    code: str  # may carry a module-level stable sub-code (e.g. "zip.ratio_exceeded")
    path: Optional[str] = None
    message: str
    hint: Optional[str] = None


class ApiError(_Base):
    code: str
    message: str
    details: list[ErrorDetail] = []
    request_id: str


class ApiErrorEnvelope(_Base):
    error: ApiError


class Job(_Base):
    id: str
    kind: Literal["import", "export", "operation"]
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: Optional[float] = None
    result_ref: Optional[str] = None
    error: Optional[ApiError] = None


# Stable error codes (contract). Add, never rename.
ERROR_CODES = (
    "bad_request", "validation_failed", "unauthenticated", "forbidden", "not_found",
    "version_conflict", "operation_conflict", "file_too_large", "unsupported_media_type",
    "unsupported_workbook", "import_failed", "rate_limited", "internal_error",
)
CellsChangedResult.model_rebuild()
