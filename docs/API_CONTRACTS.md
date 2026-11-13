# Gridora — API Contracts

Status: Phase 1 draft. Base path `/api/v1`. JSON only (except uploads/downloads). Types refer to DATA_MODEL.md.

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

`GET /jobs/{id}` → `{ id, kind:"import"|"export"|"operation", status:"queued"|"running"|"succeeded"|"failed", progress?:number, result_ref?:string, error?:ApiError }`

## 5. Workbooks

| Method | Path | Notes |
|---|---|---|
| POST | `/files/{id}/open` | creates/loads a working copy, returns `Workbook` + `CompatibilityReport` |
| GET | `/workbooks/{id}` | metadata |
| GET | `/workbooks/{id}/sheets/{sheet_id}/cells?r0&c0&rows&cols` | returns `CellWindow` (max window size enforced) |
| PATCH | `/workbooks/{id}/sheets/{sheet_id}/cells` | body `{ edits: [{r,c,value?|formula?}] }` → one history entry |
| POST | `/workbooks/{id}/save` | writes a new version; returns `FileRecord` |
| POST | `/workbooks/{id}/export` | `{format:"xlsx"|"csv", sheet_id?}` → job; includes export `CompatibilityReport` |
| GET | `/workbooks/{id}/compatibility` | latest report |

## 6. Data Tables

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/workspaces/{id}/tables` | create from file or empty |
| GET | `/tables/{id}` | metadata + columns |
| GET | `/tables/{id}/rows?offset&limit&sort` | paged rows |
| POST | `/tables/from-range` | `{workbook_id, range, header_row, dtype_overrides?}` (supports `preview:true`) |
| POST | `/tables/{id}/to-sheet` | `{workbook_id, sheet_id?|new_sheet_name, anchor}` |
| POST | `/tables/{id}/export` | csv / xlsx / parquet |

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

| Method | Path |
|---|---|
| GET/POST | `/tools` |
| GET/PUT/DELETE | `/tools/{id}` |
| POST | `/tools/{id}/run` — `{ target, inputs }` |

## 10. Charts

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/documents/{id}/charts` | |
| PUT/DELETE | `/charts/{id}` | |
| GET | `/charts/{id}/data` | aggregated dataset for rendering |

## 11. Internal module interfaces (Python)

These are the only cross-module calls. Defined in `contracts/` and imported by `apps/api`.

```python
class WorkbookEngine(Protocol):                      # implemented by packages/engine (Agent 1)
    def import_xlsx(self, path: Path) -> tuple[Workbook, CompatibilityReport]: ...
    def import_csv(self, path: Path, options: CsvOptions) -> Workbook: ...
    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow: ...
    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta: ...
    def apply_delta(self, wb: WorkbookHandle, delta: Delta, inverse: bool) -> None: ...
    def recalculate(self, wb: WorkbookHandle) -> None: ...
    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport: ...
    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> None: ...

class OperationExecutor(Protocol):                   # implemented by packages/dataops (Agent 2)
    def describe_all(self) -> list[OperationDescriptor]: ...
    def validate(self, op: Operation) -> list[ValidationError]: ...
    def preview(self, op: Operation, ctx: ExecContext, limit: int) -> PreviewResult: ...
    def apply(self, op: Operation, ctx: ExecContext) -> OperationResult: ...
    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]: ...

class TableStore(Protocol):                          # implemented by packages/dataops
    def create_from_rows(...); def read_page(...); def sheet_range_to_table(...); def table_to_cells(...)
```
`ExecContext` is the bridge: it gives `dataops` read/write access to sheet ranges through `WorkbookEngine` (passed in by the API), so `dataops` never imports `engine`.

## 12. Versioning

Breaking changes bump `/api/v1` → `/api/v2`. Operation param schemas carry `schema_version`; migration functions live beside each operation.
