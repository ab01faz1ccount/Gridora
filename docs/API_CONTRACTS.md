# Gridora — API Contracts

Base path `/api/v1`. JSON only (except uploads and downloads). Types refer to DATA_MODEL.md; `contracts/` is normative.

## 1. Envelope

Success: `{ "data": <T>, "meta"?: { "request_id": string, "next_cursor"?: string } }`

Error: 
```json
{ "error": { "code": "validation_failed", "message": "Human-readable",
             "details": [ { "code": "...", "path": "/params/column", "message": "...", "hint": "..." } ],
             "request_id": "…" } }
```

| HTTP | `error.code` examples |
|---|---|
| 400 | `bad_request`, `validation_failed` |
| 401 | `unauthenticated` |
| 403 | `forbidden` |
| 404 | `not_found` (also returned for other users' resources) |
| 409 | `version_conflict`, `operation_conflict` |
| 413 | `file_too_large` |
| 415 | `unsupported_media_type` |
| 422 | `unsupported_workbook`, `import_failed` |
| 429 | `rate_limited` |
| 500 | `internal_error` |

Code strings are stable and part of the contract.

## 2. Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | sets session cookie, returns user |
| POST | `/auth/logout` | |
| GET | `/auth/me` | |
| GET | `/auth/config` | public: `{registration_enabled, password_min_length}` for the sign-in page |
| POST | `/auth/register` | body `{username, password}` → 201 `AuthResult` and a session cookie; always a plain `user`; refused with `validation_failed` (`auth.username_invalid`, `auth.password_too_short`, `auth.password_common`), `operation_conflict` (`auth.username_taken`, `auth.registration_full`), `forbidden` (`auth.registration_disabled`), `rate_limited` (per IP) |
| POST | `/auth/password` | body `{current_password, new_password}` → 204; needs the session and CSRF token; ends every other session of the user |
All mutating requests require the CSRF header `X-CSRF-Token`.

## 3. Workspaces and files

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/workspaces` | list / create |
| GET/PATCH/DELETE | `/workspaces/{id}` | delete is destructive; requires `?confirm=true` |
| GET | `/workspaces/{id}/files` | |
| POST | `/workspaces/{id}/files` | multipart upload → returns `{ file, job_id }` |
| GET | `/files/{id}/download` | streams a stored version |

## 4. Jobs

| Method | Path | Notes |
|---|---|---|
| GET | `/jobs/{id}` | job status (below) |
| GET | `/jobs/{id}/compatibility` | v0.6.1: the export `CompatibilityReport` of a finished export job; 404 for other jobs |

`GET /jobs/{id}` → `{ id, kind:"import"|"export"|"operation", status:"queued"|"running"|"succeeded"|"failed", progress?:number, result_ref?:string, error?:ApiError }`

## 5. Workbooks

| Method | Path | Notes |
|---|---|---|
| POST | `/files/{id}/open` | creates/loads a working copy, returns `Workbook` + `CompatibilityReport` |
| GET | `/workbooks/{id}` | metadata |
| GET | `/workbooks/{id}/sheets/{sheet_id}/cells?r0&c0&rows&cols` | returns `CellWindow` (max window size enforced) |
| PATCH | `/workbooks/{id}/sheets/{sheet_id}/cells` | body `{ edits: [{r,c,value?|formula?}] }` → one history entry |
| GET | `/workbooks/{id}/sheets/{sheet_id}/date-columns` | v0.6.0: `DateColumns` (columns that hold dates; detection only) |
| GET | `/workbooks/{id}/sheets/{sheet_id}/find` | `q`, `match_case`, `whole_cell`, `in_formulas`, `after_row`/`after_col`, `limit` → `FindResult {matches:[{r,c}], truncated}`; row-major; Persian/Arabic digits and yeh/kaf match their Latin/Persian forms |
| POST | `/workbooks/{id}/sheets/{sheet_id}/fill` | body `{ base_seq, source: Range, target: Range }` (target adjacent to source, same columns or rows) → `CellsChangedResult`; one history entry; series for numbers, formulas shift relative refs |
| GET | `/workbooks/{id}/styles` | `ids` (comma separated `Cell.s` values, at most 500) → `StyleInfo[]`: font, colours, alignment and number format of each cell format |
| POST | `/workbooks/{id}/sheets/{sheet_id}/format` | body `{ base_seq, range: Range, change: FormatChange }` (only the sent properties change, `null` restores the default; at most 50,000 cells) → `CellsChangedResult`; one history entry |
| PUT | `/workbooks/{id}/calendar` | v0.6.0: body `{ calendar: "jalali"|"gregorian"|"hijri" }` → `Workbook`; a view option, no history entry |
| POST | `/workbooks/{id}/save` | writes a new xlsx version (kind `workbook`, parent = previous version) and bakes history in; returns `FileRecord` |
| POST | `/workbooks/{id}/export` | `{format:"xlsx"|"csv", sheet_id?}` → 202 `Job`; `result_ref` is the file id (`GET /files/{id}/download`, kind `export`); the export `CompatibilityReport` is at `GET /jobs/{id}/compatibility`; csv needs `sheet_id` |
| GET | `/workbooks/{id}/compatibility` | latest report |

## 6. Data Tables

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/workspaces/{id}/tables` | v0.6.2: list; create from `{name, columns, rows}` (≤10 000 rows; larger data comes from a range or file). Needs the real dataops |
| GET | `/tables/{id}` | metadata + columns |
| GET | `/tables/{id}/rows?offset&limit&sort` | `TableRows`; limit ≤ 1000; `sort=-col` for descending |
| POST | `/tables/from-range` | `{workbook_id, range, header_row, dtype_overrides?}` (supports `preview:true` → `TablePreview`, nothing stored); `name?`; a snapshot table whose `source` records the workbook and range |
| POST | `/tables/{id}/to-sheet` | v0.6.3: `{workbook_id, sheet_id, row?, col?, base_seq?}` → `CellsChangedResult`; one undoable history entry; refuses to overwrite non-empty cells (`would_overwrite`); a new sheet is not supported yet |
| POST | `/tables/{id}/export` | v0.6.6: 202 `Job` (like a workbook export); **csv only** (UTF-8 with BOM, text starting with `= + - @` gets an apostrophe, reported at `GET /jobs/{id}/compatibility`); for xlsx use `to-sheet` then export the workbook; parquet is not offered |
| POST | `/tables/{id}/operations/preview` | `Operation` whose target is `{kind:"data_table", table_id}` → `PreviewResult` |
| POST | `/tables/{id}/operations` | `OperationRequest` → 202 `Job` (result_ref = history seq); writes a new immutable version of the same table; destructive operations need `confirm_destructive`; an operation that would create another table is refused (`operation.unsupported_output`) |
| POST | `/tables/{id}/undo` | `?base_seq` → `TableChangedResult`; only moves the current-version pointer (nothing is rewritten) |
| POST | `/tables/{id}/redo` | same, forward |
| GET | `/tables/{id}/history` | `HistoryEntry[]`, newest first |

## 7. Operations

| Method | Path | Notes |
|---|---|---|
| GET | `/operations` | list `OperationDescriptor[]` (drives GUI forms) |
| POST | `/documents/{id}/operations/preview` | body `Operation` → `PreviewResult`, no mutation |
| POST | `/documents/{id}/operations` | body `Operation` → `OperationResult` + new `HistoryEntry` |
| POST | `/documents/{id}/pipelines/run` | body `{ pipeline, target }` |

`document_id` is a workbook id or a table id. Destructive operations (descriptor `destructive:true`) require `"confirm_destructive": true` in the body, otherwise the server returns `409 operation_conflict` with a warning describing the impact.

## 8. History

| Method | Path | Notes |
|---|---|---|
| GET | `/documents/{id}/history?cursor` | |
| POST | `/documents/{id}/undo` | |
| POST | `/documents/{id}/redo` | |

## 9. Tools (saved workflows)

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/tools` | v0.6.5: `Tool`; validated statically (known operations, parameters, declared inputs); ≤ 200 per user |
| GET/PUT/DELETE | `/tools/{id}` | |
| POST | `/tools/{id}/run` | `ToolRunRequest {workbook_id, target, inputs, base_seq, confirm_destructive}` → 202 `Job` (kind `operation`; `result_ref` = the last history seq). Sheet-range tools on a workbook only; one history entry per step; a run that does not produce plain cell changes is rolled back (`tool.unsupported_output`) |

## 10. Charts

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/documents/{id}/charts` | v0.6.4: `ChartSpec`; the path decides the document; the source must live in it (sheet range for a workbook, that table for a table); ≤ 50 per document |
| PUT/DELETE | `/charts/{id}` | PUT replaces the spec (same source checks) |
| GET | `/charts/{id}/data` | `ChartData`, computed on demand (needs the real dataops; a table source reads its current version) |

## 11. Internal module interfaces (Python)

These are the only cross-module calls. Defined in `contracts/` and imported by `apps/api`.

```python
class WorkbookEngine(Protocol):                      # implemented by packages/engine
    def import_xlsx(self, path: Path, *, file_id: str | None = None) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]: ...
    def import_csv(self, path: Path, options: CsvOptions) -> Workbook: ...
    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow: ...
    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta: ...
    def apply_delta(self, wb: WorkbookHandle, delta: Delta, inverse: bool) -> None: ...
    def recalculate(self, wb: WorkbookHandle) -> None: ...
    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport: ...
    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> None: ...

class OperationExecutor(Protocol):                   # implemented by packages/dataops
    def describe_all(self) -> list[OperationDescriptor]: ...
    def validate(self, op: Operation) -> list[ValidationError]: ...
    def preview(self, op: Operation, ctx: ExecContext, limit: int) -> PreviewResult: ...
    def apply(self, op: Operation, ctx: ExecContext) -> OperationResult: ...
    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]: ...

class TableStore(Protocol):                          # implemented by packages/dataops
    def create_from_rows(...); def read_page(...); def sheet_range_to_table(...); def table_to_cells(...)
```
`ExecContext` is the bridge: it gives `dataops` read/write access to sheet ranges through `WorkbookEngine` (passed in by the API), so `dataops` never imports `engine`.

## 11a. Contract v0.2 additions (Phase 2 review; `contracts/` is normative, this section summarizes)

- `POST /auth/login` and `GET /auth/me` return `AuthResult {user, csrf_token}`.
- Mutating document calls take `base_seq` (`CellEditRequest`, `OperationRequest`); a stale value returns `409 version_conflict`.
- `PATCH cells`, `undo`, `redo`, sheet operations return `CellsChangedResult {history_entry, sheet_id, cells}`, where `cells` includes recalculated dependents.
- Max window is 1000 rows x 100 cols (`MAX_WINDOW_*`).
- `GET /operations?locale=fa` returns descriptors; `GET /operations/i18n?locale=fa` returns the flat key->text catalog from `gridora_dataops.catalog(locale)`.
- Export jobs: `Job.result_ref` is a `FileRecord` id, downloaded via `GET /files/{id}/download`.
- `ValidationError.path` is a JSON pointer relative to the root of the Operation (`/params/column`).
- Optional engine extensions (`FormattingEngine`, `StructureEngine`) are feature-detected by `apps/api`.
- User management in v1 is a CLI plus bootstrap-admin env; there are no HTTP admin endpoints.

## 11b. Stable detail codes (v0.4.1)
`ErrorDetail.code` values that clients may rely on, in addition to module sub-codes documented in each module README:
- `too_large_for_history` under top-level `operation_conflict` (HTTP 409): an in-place sheet write would exceed the 200,000-cell history cap. The UI should offer "convert this range to a Data Table" (Data Tables have no such cap).

## 12. Versioning

Breaking changes bump `/api/v1` → `/api/v2`. Operation param schemas carry `schema_version`; migration functions live beside each operation.
