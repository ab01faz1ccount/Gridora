"""Shared data contracts for Gridora (normative; mirrors docs/DATA_MODEL.md).

Owned by Agent 0. Other agents must not edit this file; propose changes via a
CONTRACT_CHANGE note in the PR description.

Conventions: rows/cols are 0-based ints; IDs are UUID strings; timestamps are ISO-8601 UTC.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1
CONTRACT_VERSION = "0.2.0"
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
    kind: Literal["workbook", "table", "original"]
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


# ----------------------------------------------------------- operations ----
class SheetRangeTarget(_Base):
    kind: Literal["sheet_range"] = "sheet_range"
    range: Range


class DataTableTarget(_Base):
    kind: Literal["data_table"] = "data_table"
    table_id: str


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


class CellPatchDelta(_Base):
    kind: Literal["cell_patch"] = "cell_patch"
    sheet_id: str
    before: list[Cell]
    after: list[Cell]


class TableVersionDelta(_Base):
    """from_version == 0 means "the table did not exist" (operation created it);
    undo then removes it from view, redo restores it. restore_version is a pointer swap."""

    kind: Literal["table_version"] = "table_version"
    table_id: str
    from_version: int = Field(ge=0)
    to_version: int = Field(ge=1)


class SheetStructureDelta(_Base):
    kind: Literal["sheet_structure"] = "sheet_structure"
    sheet_id: str
    change: dict[str, Any]  # shape defined by Agent 1 in engine docs; reviewed by Agent 0


Delta = Annotated[
    Union[CellPatchDelta, TableVersionDelta, SheetStructureDelta], Field(discriminator="kind")
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


class Pipeline(_Base):
    id: Optional[str] = None
    name: str
    input_kind: Literal["sheet_range", "data_table"]
    steps: list[PipelineStep]


class ToolInput(_Base):
    name: str
    kind: Literal["column", "range", "value"]
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


# ------------------------------------------------- styles and layout ----
class StyleInfo(_Base):
    """Resolved formatting for one style id (Cell.s). Optional engine extension."""

    id: int
    number_format: Optional[str] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    font_color: Optional[str] = None  # "#RRGGBB"
    fill_color: Optional[str] = None  # "#RRGGBB"
    halign: Optional[Literal["left", "center", "right", "justify"]] = None
    wrap: bool = False


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


class CellEditRequest(_Base):
    base_seq: int  # last history seq the client has seen; mismatch -> 409 version_conflict
    edits: list[CellEdit]


class OperationRequest(_Base):
    base_seq: int
    operation: Operation
    confirm_destructive: bool = False


class CellsChangedResult(_Base):
    """Response of PATCH cells / undo / redo / operations on sheets."""

    history_entry: "HistoryEntry"
    sheet_id: str
    cells: list[Cell]  # changed cells INCLUDING recalculated dependents (== delta.after)


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
