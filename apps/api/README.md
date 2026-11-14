# apps/api — Gridora HTTP API and composition layer

Owner: Agent 3. Plan: [`../PLAN.md`](../PLAN.md). Contracts: `../../contracts/` (v0.2.0, read-only).

## Status: In progress (PRs 1-5: skeleton, auth, workspaces/files, composition + stubs, jobs + workbooks)

### What works (each item has a test)
- App factory (`gridora_api.main:create_app`), configuration from `GRIDORA_*` environment variables.
- Standard success envelope and error envelope; every response carries `X-Request-ID`.
- One status table for the 13 contract error codes, checked against `gridora_contracts.ERROR_CODES`.
- Request-validation errors return `400 validation_failed` with JSON-pointer paths (not FastAPI's 422).
- Unhandled exceptions return `500 internal_error` with no stack trace or exception text.
- `/healthz` and `/readyz` (outside `/api/v1`, not part of the contract).
- Contract route conformance: routes in the app must be a subset of the route table parsed from
  `docs/API_CONTRACTS.md` (+ the v0.2 additions); the number still unimplemented is reported.

- Auth (PR 2): `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` returning contract `AuthResult`.
  argon2id hashes; server-side sessions (only SHA-256 of the cookie token stored); HttpOnly,
  Secure, SameSite=Strict cookie (`__Host-` prefix); session rotated at login; idle (sliding) and
  absolute expiry; synchronizer CSRF token checked on every mutating route that uses the `auth`
  dependency; Postgres-backed login rate limit (`429` + `Retry-After`); audit log rows for login
  and logout; operator CLI (`python -m gridora_api.cli create-user | reset-password | check-config`);
  optional first-start bootstrap admin from env.
- Alembic migration `0001` (users, sessions, login_attempts, audit_log); a test fails if models and
  migrations diverge.
- Isolation harness: every `/api/v1` route with an id parameter must have an isolation case
  (registry is empty until PR 3 adds owned resources).

- Workspaces and files (PR 3): workspace CRUD (delete needs `?confirm=true`, removes rows and
  stored bytes), file list, streaming multipart upload, download. Owner-scoped repositories
  (`db/repos/owned.py`: no fetch-by-id-alone exists; another user's id is `404`, same as missing).
- Upload: streamed to quarantine, never buffered; `file_too_large` the moment the file part
  passes the cap (exactly 100 MiB passes, +1 byte fails; tested at the real default with a streamed
  body); early reject on a large `Content-Length`; extension allowlist (`.xlsx .xlsm .csv`) plus
  magic-byte check (`415`); truncated or multi-file bodies are `400` and leave nothing behind;
  display names are sanitized and never used in paths.
- Storage: only `storage/layout.py` builds paths (UUID components + allowlists); files are `0600`,
  placed by temp+fsync+rename and never overwritten; `PathResolver` for dataops is implemented there.
- Isolation: the OpenAPI-driven harness now covers all 6 id routes (404 for another user, 401
  without a session, nothing changed). A test client scans every JSON body and every header of
  every response in the suite and fails the test on any server path or storage detail.

- Composition (PR 4): `composition/wiring.py` is the only module that loads `gridora_engine` /
  `gridora_dataops` (lazily, through the four fixed factories of contracts v0.2; a test enforces
  that nothing else in the package imports or names them). `GRIDORA_ENGINE` / `GRIDORA_DATAOPS` =
  `stub|real`, one setting each; `real` without the package fails at startup with a clear message;
  a missing factory or an object that does not satisfy the protocol is refused. `PathResolver` is
  handed to `create_table_store`. `FormattingEngine` / `StructureEngine` are feature-detected.
- `EngineExecContext`: typed `read_range` (tiled beyond the 1000 x 100 window cap), value-only
  `write_range` that clears uncovered cells in one delta, 200,000-cell cap per undoable step
  (`operation_conflict` with detail code `too_large_for_history`).
- **STUBS (clearly marked, not real implementations):**
  - `StubEngine`: in-memory, single sheet, **CSV only** (UTF-8 with/without BOM, Windows-1256,
    delimiter sniffing). XLSX import/export raise `unsupported_workbook`. Formulas are **not**
    evaluated or stored (a formula edit is rejected with a JSON-pointer error; text that looks like a
    formula stays text). No styles. Every import reports a `partial` compatibility item.
  - `StubExecutor`: `sort`, `find_replace`, `remove_duplicates` on sheet ranges (real JSON-Schema
    params, validate/preview/apply with undoable deltas, `range_has_formulas` refusal, pipelines with
    one delta per step, `bind_tool`). No Persian-aware collation. `StubTableStore` and `chart_data`
    answer `bad_request` ("needs the real dataops package").
  - Visible at runtime: every response carries `X-Gridora-Engine` / `X-Gridora-Dataops`;
    `/readyz` lists `implementations`.

- Jobs and workbooks (PR 5): `jobs` table + in-process dispatcher (`jobs/runner.py`,
  `PostgresJobRunner` behind a `JobRunner` interface). Claims with `FOR UPDATE SKIP LOCKED` (two
  dispatchers never run the same job: tested with 30 jobs); concurrency cap; jobs left `running` by a
  dead process are failed at startup (not retried), queued ones run; failures are recorded as
  contract `ApiError` (internal crashes are generic, no internals). `GET /jobs/{id}`.
- Upload now queues an `import` job (`job_id` is real). The import runs in a worker thread with a
  time limit; the job result is the workbook id. `POST /files/{id}/open` (idempotent),
  `GET /workbooks/{id}`, `GET /workbooks/{id}/compatibility`, and `GET .../sheets/{sheet_id}/cells`
  (window caps 1000 x 100 enforced, lower configured caps win; empty windows are not errors).
- Working copies (`services/working_copies.py`): LRU cap (`GRIDORA_MAX_OPEN_WORKBOOKS`), per-document
  threading lock around every engine call (handles are not thread-safe), eviction closes the handle,
  a cache miss rebuilds the copy from the stored file (tested: restart/eviction gives identical cells
  and the same sheet ids). Workspace delete drops copies, documents and workbooks.
- The API owns identity: `Workbook.id` is the document id, `file_id` the stored original, `name` the
  user's display name.

### What does not work yet
- No cell edits, history, undo/redo, save, export, operations, tables or charts (PR 10 onward).
  A rebuilt working copy is the stored file only; **history replay is not implemented yet** (no edits
  exist yet, so nothing is lost).
- Import time limit stops *waiting*; the worker thread itself cannot be killed (ADR-011, Phase 4).
- With the stub engine, XLSX uploads are stored but their import job fails with
  `unsupported_workbook`. `POST .../files` returns `job_id: null` until the
  import job exists (PR 5). The file is stored but not parsed or validated beyond type/magic.
- Lists are not paginated (capped at 1000 rows).
- Only `.xlsx`, `.xlsm`, `.csv` are accepted; UTF-16 CSV is refused (needs a NUL-free text file).
- Rate limiting counts per username and per IP; behind nginx set `GRIDORA_TRUST_PROXY_HEADERS=true`.
- `POST /auth/logout` returns `204` with no body (the contract does not define a response).
- Admin role exists but nothing uses it yet; there are no HTTP admin endpoints (Agent 0 decision).
- The 405 response keeps status 405 with code `bad_request` (the contract has no 405 code).

### Deviations from `apps/PLAN.md`
- Routers import `db.repos` / `db.models` (owner-scoped repositories) instead of going through a
  service layer for plain CRUD. The plan's "routers may not import db/" rule is not enforced; the
  isolation matrix and the repository design are the actual guarantees.

### Known limitations (by design for v1, from the plan)
- Single API worker process (working copies will live in memory). No horizontal scaling.
- No OS-level isolation for hostile-file parsing in v1 (ADR-011); relies on engine limits. Phase 4.

## Development
```bash
pip install -e ../../contracts/python
pip install -e ".[dev]"
pytest
ruff check . && mypy src
# tests need PostgreSQL: GRIDORA_TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host/db_test
GRIDORA_DATA_ROOT=./data uvicorn --factory gridora_api.main:run --reload
```
