// Shared data contracts for the web app. Mirrors contracts/python/gridora_contracts/models.py.
// Owned by Agent 0 — propose changes via a CONTRACT_CHANGE note in the PR.
// Rows/cols are 0-based. IDs are UUID strings. Timestamps are ISO-8601 UTC.

export const SCHEMA_VERSION = 1;
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

export type CellValue =
  | { k: "num"; n: number }
  | { k: "str"; s: string }
  | { k: "bool"; b: boolean }
  | { k: "err"; e: "#DIV/0!" | "#N/A" | "#NAME?" | "#NULL!" | "#NUM!" | "#REF!" | "#VALUE!" }
  | { k: "date"; iso: string };

export interface Cell { r: number; c: number; v?: CellValue; f?: string; s?: number; t?: string }
export interface CellEdit { r: number; c: number; value?: CellValue; formula?: string }
export interface Range { sheet_id: string; r0: number; c0: number; r1: number; c1: number }
export interface Window { row0: number; col0: number; rows: number; cols: number }
export interface CellWindow { sheet_id: string; row0: number; col0: number; rows: number; cols: number; cells: Cell[] }

export interface SheetMeta {
  id: string; name: string; index: number;
  visible: "visible" | "hidden" | "very_hidden";
  row_count: number; col_count: number;
  frozen?: { rows: number; cols: number };
  rtl: boolean;
}
export interface DefinedName { name: string; scope: string; ref: string }

export interface CompatItem {
  code: string; status: "supported" | "partial" | "unsupported";
  preserved: boolean; editable: boolean; message: string; location?: string;
}
export interface CompatibilityReport {
  source: "import" | "export"; generated_at: string; items: CompatItem[];
  summary: { supported: number; partial: number; unsupported: number };
}
export interface Workbook {
  schema_version: number; id: string; file_id: string; name: string;
  sheets: SheetMeta[]; defined_names: DefinedName[];
  date_system: "1900" | "1904"; compat?: CompatibilityReport;
}

export type DType = "int64" | "float64" | "bool" | "string" | "date" | "datetime" | "decimal";
export interface Column { name: string; dtype: DType; nullable: boolean; display_format?: string }
export interface TableSource { kind: "sheet_range"; workbook_id: string; range: Range; link: "snapshot" | "refreshable" }
export interface DataTable {
  schema_version: number; id: string; workspace_id: string; name: string; version: number;
  columns: Column[]; row_count: number; source?: TableSource;
}

export interface Workspace { id: string; owner_id: string; name: string; created_at: string }
export interface FileRecord {
  id: string; workspace_id: string; owner_id: string; kind: "workbook" | "table" | "original";
  display_name: string; size_bytes: number; sha256: string; created_at: string; parent_id?: string;
}

export interface ValidationError { code: string; path: string; message: string; hint?: string }
export interface Warning { code: string; severity: "info" | "warn"; message: string; location?: string }

export type Target =
  | { kind: "sheet_range"; range: Range }
  | { kind: "data_table"; table_id: string };

export interface Operation { id?: string; type: string; schema_version: number; target: Target; params: Record<string, unknown> }
export interface OperationDescriptor {
  type: string; label: string; category: string; description: string;
  params_schema: Record<string, unknown>; targets: ("sheet_range" | "data_table")[];
  destructive: boolean; supports_preview: boolean;
}

export type Delta =
  | { kind: "cell_patch"; sheet_id: string; before: Cell[]; after: Cell[] }
  | { kind: "table_version"; table_id: string; from_version: number; to_version: number }
  | { kind: "sheet_structure"; sheet_id: string; change: Record<string, unknown> };

export interface OperationResult {
  status: "ok" | "error"; affected: { cells?: number; rows?: number };
  delta?: Delta; warnings: Warning[]; errors: ValidationError[]; output?: Target;
}
export interface PreviewResult { columns: string[]; rows: unknown[][]; total_rows?: number; warnings: Warning[] }

export interface PipelineStep { type: string; schema_version: number; params: Record<string, unknown>; label?: string }
export interface Pipeline { id?: string; name: string; input_kind: "sheet_range" | "data_table"; steps: PipelineStep[] }
export interface ToolInput { name: string; kind: "column" | "range" | "value"; label: string; required: boolean }
export interface Tool { id?: string; owner_id?: string; name: string; description: string; pipeline: Pipeline; inputs: ToolInput[]; created_at?: string }

export interface HistoryEntry {
  id: string; document_id: string; seq: number; operation: Operation; delta: Delta;
  label: string; created_at: string; undone: boolean;
}

export interface ChartSeries { name?: string; value_col: string | number; category_col?: string | number; aggregate?: "sum" | "avg" | "count" | "min" | "max" }
export interface ChartSpec {
  schema_version: number; id?: string; document_id: string;
  type: "bar" | "line" | "pie" | "scatter" | "area"; title?: string; source: Target;
  series: ChartSeries[];
  options: { stacked: boolean; legend: boolean; axis_titles?: Record<string, string> };
}
export interface ChartData { categories: (string | number)[]; series: { name: string; values: (number | null)[] }[] }

export interface ErrorDetail { code: string; path?: string; message: string; hint?: string }
export interface ApiError { code: string; message: string; details: ErrorDetail[]; request_id: string }
export interface ApiErrorEnvelope { error: ApiError }
export interface ApiSuccess<T> { data: T; meta?: { request_id: string; next_cursor?: string } }
export interface Job {
  id: string; kind: "import" | "export" | "operation";
  status: "queued" | "running" | "succeeded" | "failed";
  progress?: number; result_ref?: string; error?: ApiError;
}

export const ERROR_CODES = [
  "bad_request", "validation_failed", "unauthenticated", "forbidden", "not_found",
  "version_conflict", "operation_conflict", "file_too_large", "unsupported_media_type",
  "unsupported_workbook", "import_failed", "rate_limited", "internal_error",
] as const;
