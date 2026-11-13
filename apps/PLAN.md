# Agent 3 — Implementation Plan (Step 0)

Owner: Agent 3. Scope: `apps/web/`, `apps/api/`, `deploy/`.
Status: **PLAN v2 (revised after `docs/reviews/PHASE2_REVIEW.md`). No implementation is claimed to work until a test proves it.**
Verdict from Agent 0: *approved with conditions* C3.1–C3.3, all applied below. Working against `contracts/` **v0.2.0**.

### Changes in v2
- **C3.1** ProcessPool import isolation removed from v1 (ADR-011). Imports run in a worker thread with the engine's limits plus a timeout; process isolation is a documented Phase 4 limitation (§2.7).
- **C3.2** Single worker + in-memory working copies kept; README limitation stays; the LRU cap and eviction/rehydration tests are part of PR 9 (§2.8, §1).
- **C3.3** `deploy-stack` moved before `web-import`, so `docker compose up` is verified early with the stub engine (§1).
- Contract v0.2.0 adopted everywhere (§2.9, §2.10, §3.3, §3.5, §10): `AuthResult`, `CellsChangedResult`, `base_seq`, window cap 1000 × 100, factory entry points + `PathResolver`, `FormattingEngine` feature detection, `Operation.extra_targets`, `GET /operations/i18n`.
- §10 now records the decision on each of my CONTRACT_CHANGE requests and the few follow-ups that remain.

Inputs read: `agents/AGENT_3_PLATFORM.md`, `docs/WORKFLOW.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/SECURITY_MODEL.md`, `docs/MODULE_BOUNDARIES.md`, `docs/I18N_SPEC.md`, `docs/TESTING_STRATEGY.md`, `docs/DATA_MODEL.md`, `docs/INTEGRATION_PLAN.md`, `docs/DECISIONS.md`, and `contracts/` (Python + TypeScript).

---

## 0. Summary of decisions

| Topic | Decision |
|---|---|
| Frontend stack | React 18 + TypeScript (strict) + Vite |
| Server state | TanStack Query (workspaces, files, jobs, history, tools) |
| UI/ephemeral state | Zustand (selection, active sheet, panels, display prefs, pending edits) |
| Grid cell data | Own `BlockCache` store (not in TanStack Query), read via `useSyncExternalStore` |
| Grid rendering | Custom, DOM-based, windowed rows and columns; canvas only if the 100k-row benchmark fails |
| Forms | Own renderer for a documented subset of JSON Schema, driven by `OperationDescriptor.params_schema` |
| i18n | Own thin typed catalog (`fa.json`, `en.json`) + browser `Intl` APIs; no i18n framework |
| Jalali display | `Intl.DateTimeFormat` with the `persian` calendar (no library); explicit conversion operations are Agent 2's |
| Charts | Apache ECharts, tree-shaken, bundled |
| Backend | FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL |
| Job runner | Postgres-backed `jobs` table + in-process runner (worker threads) behind a `JobRunner` interface (no Redis/Celery) |
| Passwords/sessions | argon2id; server-side sessions; HttpOnly cookie; synchronizer CSRF token |
| Stub swap | One env var per module: `GRIDORA_ENGINE=stub\|real`, `GRIDORA_DATAOPS=stub\|real` |
| Deploy | Docker Compose: `nginx`, `api`, `postgres`, `backup`; nothing outbound at runtime |

---

## 1. Delivery order (small PRs, one concern each)

Follows the slice order of `docs/INTEGRATION_PLAN.md`. Each PR carries tests, a README "what works / what doesn't" update and a truthful status-table update.

| # | PR | Folder | Slice |
|---|---|---|---|
| 1 | `api-skeleton`: app factory, config, request-id, envelope, error mapping, `/healthz` `/readyz`, OpenAPI conformance harness | api | — |
| 2 | `api-auth`: schema + first Alembic migration, argon2id, sessions, `AuthResult`/CSRF, login rate limit, audit log, owner-scoped repository base, CLI user creation, isolation-test harness | api | — |
| 3 | `api-files`: storage layout + `PathResolver`, streaming upload with limits, download, no-path-leak scanner fixture | api | 1 |
| 4 | `api-composition`: factory wiring, stub `WorkbookEngine` (CSV only), stub `OperationExecutor`/`TableStore`, config swap, import-boundary test | api | 1 |
| 5 | `api-workbooks`: jobs table + runner, import job (worker thread), open, windowed `cells` GET | api | 1 |
| 6 | `web-skeleton`: Vite app, shell, RTL, i18n catalog, API client (CSRF via `AuthResult`), login, workspaces | web | — |
| 7 | `deploy-stack` *(moved up, C3.3)*: compose, nginx, `.env.example`, healthchecks, TLS notes, backup/restore scripts; `docker compose up` verified with the stub engine | deploy | — |
| 8 | `web-grid`: `DataSource`, `BlockCache`, virtualization, selection, keyboard (LTR + RTL), 100k benchmark | web | 1 |
| 9 | `web-import`: upload UI, job polling, compatibility panel | web | 1–2 |
| 10 | `api-history` + `web-edit`: cell edits with `base_seq`, history service, undo/redo, optimistic edits, history panel; **includes working-copy LRU cap, eviction and rehydration tests (C3.2)** | both | 3 |
| 11 | `web-operations`: descriptor-driven forms (`x-gridora-*` subset), preview, destructive confirm | web | 4 |
| 12 | Data Tables view + bridge, charts, versioned save + export, saved Tools | both | 5–8 |
| 13 | `e2e`: Playwright Definition-of-Success flow | web | — |

Agent 0's current go-ahead covers PRs 1–6 of this table. CI workflows are proposed as `apps/ci/<name>.yml.proposed` (WORKFLOW.md); Agent 0 commits them.

---

## 2. Backend (`apps/api`)

### 2.1 Layout

```
apps/api/
  pyproject.toml                 # deps pinned via lockfile
  alembic.ini
  migrations/                    # Alembic, one revision per schema change
  src/gridora_api/
    main.py                      # app factory
    config.py                    # pydantic-settings; all env in one place
    core/
      envelope.py                # ApiSuccess / meta.request_id
      errors.py                  # DomainError(code, http_status) + handlers
      middleware.py              # request-id, security headers, access log
      csrf.py  ratelimit.py  security.py
    api/v1/                      # thin routers, no business logic
      auth.py workspaces.py files.py jobs.py workbooks.py
      tables.py operations.py history.py tools.py charts.py
    db/
      models.py session.py
      repos/                     # every function REQUIRES owner_id; no unscoped getters
    services/                    # business logic; routers call only these
      auth.py workspaces.py files.py uploads.py jobs.py
      workbooks.py history.py tables.py tools.py charts.py audit.py
    storage/
      layout.py                  # UUID-derived paths; the only place that builds a path
      atomic.py                  # temp file + fsync + rename
    jobs/
      runner.py                  # JobRunner interface + Postgres impl
      handlers.py                # import / export / operation
    composition/                 # THE ONLY package allowed to import gridora_engine / gridora_dataops
      wiring.py                  # calls the fixed factories (create_engine / create_executor / create_table_store / catalog)
      exec_context.py            # ExecContext implementation (engine-backed)
      stubs/engine_stub.py       # clearly marked STUB
      stubs/executor_stub.py     # clearly marked STUB (executor + minimal table store + catalog)
    cli.py                       # create-user, reset-password, check-config
  tests/
```

Rules enforced by a test (AST scan, no extra dependency):
- Only `composition/` may import `gridora_engine` or `gridora_dataops`.
- `gridora_engine` and `gridora_dataops` are never imported together outside `composition/`.
- Routers may not import `db/` directly.
- Nothing returns or logs a filesystem path to a client.

### 2.2 Envelope and errors
- Success `{data, meta:{request_id}}`; failure `{error:{code,message,details,request_id}}`, exactly as `API_CONTRACTS.md` §1.
- `DomainError(code)` maps to HTTP status through one table that is checked against `ERROR_CODES` from `contracts/`.
- FastAPI's default 422 request-validation response is **replaced**: request validation errors become `400 validation_failed` with `details[].path` as a JSON pointer. HTTP 422 is used only for `unsupported_workbook` and `import_failed`, per the contract.
- Unknown routes and other users' resources: `404 not_found`. Unhandled exceptions: `500 internal_error`, no stack trace, `request_id` logged server-side.
- Every response gets `X-Request-ID`.

### 2.3 Auth, sessions, CSRF
- argon2id via `argon2-cffi`; parameters configurable and recorded; rehash on login if parameters change.
- Session token: 256-bit random, only its SHA-256 stored in Postgres. Cookie: `HttpOnly`, `Secure` (disable only via an explicit dev flag), `SameSite=Strict`, `__Host-` prefix when Secure. Rotated at login (no fixation); idle and absolute timeouts; logout deletes the row.
- CSRF: synchronizer token stored in the session row and returned to the client in `AuthResult` by `POST /auth/login` and `GET /auth/me`; compared in constant time against `X-CSRF-Token` on every mutating method. Exempt: `POST /auth/login` only (protected by rate limit + SameSite).
- Login rate limiting: Postgres counters keyed by (normalized username, IP) with backoff → `429 rate_limited`. nginx adds a coarse second layer.
- Roles `user` / `admin`. Admin gets user management and backup settings only; no code path lets an admin read another user's files.
- User creation in v1: CLI (`python -m gridora_api.cli create-user`) and an optional bootstrap-admin env on first start. **No HTTP admin endpoints** (Agent 0 decision).

### 2.4 Isolation
- Every owned table has `owner_id NOT NULL` and a composite index `(owner_id, id)`.
- Repositories take `owner_id` as a required argument and filter by it; a missing or foreign row raises `not_found`.
- Mandatory CI test: iterate **every route in the generated OpenAPI**, create two users, create a resource with user A, access it with user B, expect `404`. The test fails if a route with an ID path parameter has no isolation case, so new routes cannot silently skip it.
- Postgres row-level security as defense in depth is noted but **not** planned for v1 (extra complexity; revisit in Phase 4).

### 2.5 File storage
- Layout: `${DATA_ROOT}/users/<owner_uuid>/<kind>/<file_uuid>[.<ext>]`, built only by `storage/layout.py`. Clients get IDs only.
- Uploads: stream to `${DATA_ROOT}/quarantine/<uuid>` while counting bytes and hashing (SHA-256). Abort with `413 file_too_large` the moment the count passes `MAX_UPLOAD_BYTES` (100 MB, from `contracts/`). Also enforced by `Content-Length` pre-check and nginx `client_max_body_size`. The parser must be a streaming one; buffering the whole body is not acceptable. Library choice is deferred to PR 3 and goes through DECISIONS.md.
- Type check does not trust the client `Content-Type`: extension allowlist plus magic-byte check (ZIP signature for XLSX; text/encoding probe for CSV) → `415 unsupported_media_type`.
- Structural validation of XLSX (zip limits, XML limits) is the **engine's** job at import. The API's job is to run import in a job with a timeout and memory limit and to surface `unsupported_workbook` / `import_failed`.
- After validation: move to the final path (atomic rename), insert `FileRecord(kind="original")`. Originals are never rewritten.
- Saving creates a new `FileRecord(kind="workbook", parent_id=<previous>)` via temp file + fsync + rename (`atomic.py`).
- Download streams with a sanitized `Content-Disposition` (RFC 5987 for Persian names); `display_name` is never used as a path component.

### 2.6 PostgreSQL schema outline
(Outline only; the exact DDL lands in migrations.)

| Table | Key columns |
|---|---|
| `users` | id, username (unique, citext), password_hash, role, is_active, created_at |
| `sessions` | id, user_id, token_sha256, csrf_token, created_at, last_seen_at, expires_at, ip, user_agent |
| `login_attempts` | key, window_start, count |
| `workspaces` | id, owner_id, name, created_at |
| `files` | id, owner_id, workspace_id, kind, display_name, size_bytes, sha256, parent_id, storage_key (internal, never serialized), created_at |
| `documents` | id, owner_id, kind (`workbook`\|`table`) — single registry so `{document_id}` routes resolve in one lookup |
| `workbooks` | id (= documents.id), owner_id, workspace_id, file_id (original), current_file_id, last_saved_seq, name, compat_json, created_at |
| `data_tables` | id (= documents.id), owner_id, workspace_id, name, current_version, source_json, created_at |
| `table_versions` | table_id, version, storage_key, columns_json, row_count, sha256, created_at |
| `history_entries` | id, document_id, owner_id, seq, operation_json, delta_json \| delta_blob_file_id, label, undone, created_at; unique (document_id, seq) |
| `tools` | id, owner_id, name, description, pipeline_json, inputs_json, created_at |
| `chart_specs` | id, owner_id, document_id, spec_json, created_at |
| `jobs` | id, owner_id, kind, status, progress, payload_json, result_ref, error_json, attempts, created_at, started_at, finished_at |
| `audit_log` | id, ts, actor_id, action, target_kind, target_id, ip, request_id, outcome |

Notes:
- Deltas larger than a threshold (default 256 KB, configurable) go to a blob file; the row stores the reference. This keeps a 100k-row sort from bloating Postgres.
- Audit events (per `SECURITY_MODEL.md`): logins (success and failure), logout, uploads, deletes, exports.
- Who owns the Parquet bytes versus the metadata rows for Data Tables is an open question (§10, item 5).

### 2.7 Job runner
Options considered: Celery + Redis, arq + Redis, Postgres queue library, own minimal runner.

**Choice: Postgres-backed `jobs` table and a small in-process runner behind a `JobRunner` interface.**
- No new infrastructure (Redis would be one more container to ship, back up and secure in an offline deployment).
- Claim with `SELECT … FOR UPDATE SKIP LOCKED`; status transitions `queued → running → succeeded|failed`; progress is coarse because the protocols have no progress callback (§10, item 8).
- On startup, jobs left `running` by a crashed process are marked `failed` (`internal_error`) rather than silently retried, because imports and operations are not guaranteed idempotent.
- Constraint that drives the design: a `WorkbookHandle` is an in-memory object owned by the engine and is not guaranteed to be picklable or shareable. Operations on an open workbook therefore must run in the process that holds the handle, serialized per document (per-document asyncio lock + worker thread). CPU-bound engine calls run in a thread pool so the event loop stays responsive.
- **Import jobs (v1, per ADR-011):** run in a worker thread, under the engine's own budgeted limits plus an API-side timeout. A `WorkbookHandle` cannot cross a process boundary, so there is **no ProcessPool in v1**. OS-level isolation (separate process, RLIMIT) is a **Phase 4** item that needs the engine's snapshot format; until then hostile-file safety rests on the engine's limits, and the README and `SECURITY_MODEL.md` say so.
- **Honest limitation:** v1 runs a single API worker process because the working-copy cache lives in memory. Horizontal scaling is not supported and will be documented.

### 2.8 Working copies and history
- Working-copy cache: `document_id → (WorkbookHandle, last_used)`, LRU with a configurable cap (count and estimated memory). Eviction calls `engine.close(handle)` (v0.2) and is safe because state is reconstructible. Handles are **not thread-safe**: one lock and one worker thread per document. The LRU cap, eviction and rehydration tests ship in PR 10 (C3.2); the "no horizontal scaling" limitation is stated in the README.
- Rehydration after a restart or eviction: load `current_file_id` (last saved version) with `import_xlsx`/`import_csv`, then replay `history_entries` with `seq > last_saved_seq` and `undone = false` via `engine.apply_delta(..., inverse=False)`. Replay-equals-live is a required test on my side; it depends on Agent 1's replay-determinism guarantee (C1.3), and deltas include recalculated dependents while `apply_delta` does not recalculate (normative in v0.2).
- Every mutation (cell edit, operation, undo, redo) goes through `history.py`, inside one DB transaction with the engine call serialized per document:
  - new entry gets `seq = max+1`; entries with `undone = true` are deleted first (redo tail truncated);
  - undo = apply inverse of the highest non-undone entry (`cell_patch` via `engine.apply_delta`; `table_version` via `TableStore.restore_version`);
  - the cap (500 entries or 200 MB of deltas, from `DATA_MODEL.md` §6) triggers a forced save of a version, then the oldest entries are dropped.
- Mutating requests carry `base_seq`; a mismatch returns `409 version_conflict`. This protects against two tabs on one document. (Needs a contract note, §10 item 4.)
- Save never overwrites: new file version, `last_saved_seq` updated, original untouched.

### 2.9 Composition layer and stubs
- `composition/wiring.py` is the single place that reads `GRIDORA_ENGINE` / `GRIDORA_DATAOPS`. For `real` it calls exactly the fixed factories from `protocols.py`: `gridora_engine.create_engine(config)`, `gridora_dataops.create_executor(config)`, `gridora_dataops.create_table_store(path_for)`, `gridora_dataops.catalog(locale)`; nothing else is imported from those packages. The stubs expose the same factories. `path_for(owner_id, table_id, version)` is implemented by `storage/layout.py`; Postgres keeps table metadata and the current-version pointer. Optional `FormattingEngine` / `StructureEngine` are feature-detected with `isinstance`; without them the API reports styles as unavailable and the web app degrades.
- Swapping stub for real = change one env value (plus installing the package). No other file changes. A test asserts that the same API test suite runs against the stub and, when it exists, the real implementation (parametrized fixture), restricted to features both support.
- `ExecContext` (`user_id`, `workspace_id`) is implemented here on top of `WorkbookEngine`: `read_range` returns typed `Cell | None` from `get_cells`; `write_range` writes values only, clears uncovered cells of the range, and returns the engine-built `cell_patch` delta. Ownership of `Operation.target` **and every `extra_targets` entry** is verified generically by the API before dispatch. Writes larger than the v1 cap of 200,000 cells per `cell_patch` return the typed `too_large_for_history` error.
- **Stub engine (CSV only, in-memory):** implements the v0.2 `WorkbookEngine` (`file_id`, `close`, delta semantics) with stdlib `csv`; UTF-8 with/without BOM and Windows-1256 detection; single sheet; `import_xlsx` raises `unsupported_workbook`; cell edits and deltas; `recalculate` is a no-op, formulas are stored as text and **not evaluated**.
- **Stub executor:** a handful of simple operations (e.g. sort, trim, find/replace, remove duplicates) over `sheet_range` only, with real JSON-Schema `params_schema`, `validate`, `preview`, `apply` and inverse deltas, so the UI form generator and destructive flow can be built and tested. It also serves a small `catalog(locale)` for `GET /operations/i18n`. No `data_table` targets, no Polars/DuckDB.
- Honesty markers: every stub file starts with a `STUB` banner; responses carry `X-Gridora-Engine: stub` (and `X-Gridora-Dataops: stub`); `/readyz` reports which implementation is loaded; the UI shows a persistent "stub engine" badge when the header says so; compatibility reports from the stub never claim `supported` for anything XLSX-specific.

### 2.10 OpenAPI conformance
- Response and request models (`AuthResult`, `CellEditRequest`, `OperationRequest`, `CellsChangedResult`, …) reuse `gridora_contracts` v0.2 pydantic models directly (wrapped in a generic envelope) so there is no second definition to drift.
- CI test A: the generated OpenAPI route table equals the route table in `API_CONTRACTS.md` (maintained as `tests/contract_routes.py`; any difference fails and must be explained). The window cap is `MAX_WINDOW_ROWS × MAX_WINDOW_COLS` = 1000 × 100, configurable lower only.
- CI test B: every response in the integration tests is validated against the contract models.
- schemathesis (proposed in `TESTING_STRATEGY.md`) is added as a dependency in the PR that wires it, with the usual DECISIONS entry.
- Infra endpoints `/healthz` and `/readyz` live outside `/api/v1` and are not part of the contract.

---

## 3. Frontend (`apps/web`)

### 3.1 Layout

```
apps/web/
  package.json  vite.config.ts  tsconfig.json  eslint config  vitest config  playwright config
  src/
    main.tsx
    app/              # providers, router, shell layout
    api/              # client.ts: fetch wrapper (unwrap envelope, CSRF header, error→typed ApiError, request_id)
    i18n/             # fa.json  en.json  index.ts (t, locale store, number/date/digit formatters)
    state/            # zustand stores: ui, prefs, pending-edits
    features/
      auth/ workspaces/ import/ operations/ tables/ charts/ history/ tools/ export/
    grid/
      geometry.ts     # index <-> pixel math (incl. scaled scrolling)
      datasource.ts   # DataSource interface
      block-cache.ts  # LRU of fetched blocks + in-flight dedupe
      Grid.tsx  Row.tsx  Cell.tsx  HeaderBar.tsx
      selection.ts  keyboard.ts  editor.tsx
    components/       # small accessible UI kit (dialog, menu, tabs, toast…)
    styles/           # tokens.css, logical-property CSS only
  public/fonts/       # bundled Persian font (woff2)
  e2e/                # Playwright
```

Types come from `contracts/typescript/index.ts` through a TS path alias (`@contracts`); **no copy** is made. Docker build context must therefore be the repo root (noted in §6).

### 3.2 State management
- **Server state → TanStack Query:** workspaces, files, jobs (polling with backoff 500 ms → 2 s), history, tools, descriptors (`GET /operations`, cached).
- **UI state → Zustand:** active workspace/document/sheet, selection, open panels, display prefs, pending edits.
- **Grid cell data is deliberately not in TanStack Query.** It changes at cell granularity and needs block-level subscriptions; it lives in `BlockCache`, exposed through `useSyncExternalStore` so only the cells whose block changed re-render.
- Display prefs (digits: Latin/Persian/Arabic-Indic; calendar: Gregorian/Jalali; locale) are stored in `localStorage` in v1. A server-side per-user pref would need a contract change (§10).

### 3.3 Grid virtualization for 100k rows
Goal: only what is on screen (plus a margin) is fetched and rendered; editing is unaffected.

- **`DataSource` interface** (`fetchBlock(r0, c0, rows, cols, signal) → block`) with two implementations: sheet windows (`GET …/cells`) and Data Table pages (`GET /tables/{id}/rows`). One grid component serves both views.
- **Geometry:** fixed default row height and per-column widths; visible range = f(scrollTop, viewport). Rows and columns are windowed (columns matter: 100+ columns are common). Rendered rows come from a small pooled set positioned absolutely with `transform`, with CSS `contain: strict` on the viewport.
- **Browser element-height limit:** a 1,048,576-row sheet exceeds the pixel-height cap of some browsers (roughly 17–33 M px depending on the browser). The scroll container therefore uses a capped proxy height and a scale factor once total height passes a threshold; `geometry.ts` owns the mapping and has unit tests at 100k, 1M rows and the boundary. Exact browser limits will be measured in PR 7 rather than assumed.
- **Fetching:** the sheet is divided into fixed-size blocks (default 100 rows × 26 cols, tuned by the benchmark; must stay under the server's 1000 × 100 window cap). Visible blocks are requested first, neighbors prefetched in the scroll direction. Requests are de-duplicated, cancelled with `AbortController` when scrolled away, and fast scrolling is debounced. Unloaded cells render as skeletons. The cache is an LRU bounded by block count.
- **Rendering choice:** DOM, not canvas, for the first implementation. Reasons: correct RTL and bidi shaping for Persian text for free, native IME, text selection, accessibility. At ~40 rows × ~20 columns the DOM stays under a thousand cells. If the Playwright benchmark misses its frame budget, the fallback is a canvas cell layer with a DOM editor overlay. That decision is taken from measurements, not preference.
- **Optimistic edits:** a `pendingEdits` map keyed by (sheet, r, c) overlays the cache and is rendered in a "pending" style. Edits are queued per document and sent serially in `PATCH …/cells` with `base_seq`. On success, the returned changed cells (including recalculated ones) are merged into the cache and pending entries are dropped. On failure, pending entries are rolled back, an i18n error toast is shown, and `409 version_conflict` triggers a refetch of visible blocks. Undo/redo invalidates the blocks touched by the returned delta.
- **Keyboard and selection:** anchor + focus range; arrows, Shift+arrows, Tab/Enter, Home/End, PageUp/PageDown, F2/Enter to edit, Esc to cancel, Delete to clear. Ctrl+arrow "jump to data edge" requires knowing data beyond the loaded blocks, so it is deferred. Fill handle, paste of ranges larger than a window, and column-resize persistence are **not in the first cut** (consistent with "fill handle later").
- **Frozen panes** from `SheetMeta.frozen` are rendered with sticky positioning.
- **Rich formatting is limited at first:** cells carry opaque style ids `s` and format hints `t`. v0.2 adds the optional `FormattingEngine` (`StyleInfo.number_format`, `SheetLayout`); the **client** formats values from `number_format`, the engine does not render text. That work is scheduled after slice 3. Until then, and whenever the engine lacks `FormattingEngine` (always, with the stub), the grid shows raw values with basic number/date/bool formatting and ignores styles. This is stated in the web README.

### 3.4 RTL and i18n
- `document.documentElement.dir = "rtl"` and `lang="fa"` by default; `en` switches to `ltr`. All CSS uses logical properties (`margin-inline-start`, `inset-inline-end`, `text-align: start`…); a stylelint rule forbids physical `left`/`right` for layout (plugin to be recorded in DECISIONS).
- **Catalog:** `src/i18n/{fa,en}.json`, typed keys, `t(key, params)`. A CI check fails if the two catalogs have different keys, and an ESLint rule (`no-literal-string` style) fails on literal user-visible strings in JSX. Persian plural rules and number/date formatting come from `Intl.PluralRules` / `Intl.NumberFormat` / `Intl.DateTimeFormat`.
- **Fonts:** a Persian-capable font is bundled in `public/fonts/` as woff2 and loaded by `@font-face`; no CDN. Candidate: Vazirmatn (expected SIL OFL; license to be verified and recorded in `THIRD_PARTY_NOTICES.md` before it is added).
- **Digits:** storage and wire values stay Latin. Display uses `Intl.NumberFormat` with `numberingSystem` `arabext` (Persian) or `arab`. Input accepts all three digit sets and the Persian decimal/thousands separators; a `normalizeNumericInput` function runs before anything is sent. Digit mapping is never applied to formula text.
- **Dates:** wire values are ISO/serial. Jalali display uses `Intl.DateTimeFormat("fa-IR-u-ca-persian")`; this works offline in modern browsers but depends on the browser's ICU data, which Playwright tests will pin. Where Jalali display cannot round-trip to an Excel number format, it is flagged in the UI as Gridora-side display, matching `I18N_SPEC.md`.
- **Bidi:** file names, formulas and Latin fragments inside RTL text use `<bdi>` / `unicode-bidi: plaintext`.
- **Sheet direction:** each grid sets its own `dir` from `SheetMeta.rtl`, independent of UI language. In an RTL sheet column A is on the right and ArrowRight moves to the previous column (visual direction). Directional icons (undo/redo, arrows) are mirrored.
- **Cell editor / formula bar:** `dir` follows content: LTR when the text starts with `=`, otherwise auto/RTL.

### 3.5 Operation panels from `OperationDescriptor`
- `GET /operations` → a form generated from `params_schema`. The renderer supports a **documented subset** of JSON Schema: `string`, `number`/`integer`, `boolean`, `enum`, `array`, `object`, `required`, `default`, `minimum`/`maximum`, `description`. Picker widgets (column, range, expression builder) use the `x-gridora-*` keywords that Agent 2 documents in `packages/dataops/docs/PARAMS_SCHEMA.md` (due before M1); I render that subset only and show the "unsupported field" fallback for anything else. `ValidationError.path` is relative to the Operation root (`/params/column`). Operation labels and descriptions come from `GET /operations/i18n?locale=…` and are merged into the web catalog at runtime. `join`-style operations send the second table in `Operation.extra_targets`.
- A schema keyword the renderer does not support is rendered as an explicit "unsupported field" error with a code, never silently dropped. A contract-style test runs every descriptor from the stub (and later the real executor) through the renderer.
- Validation is server-authoritative: the form calls the preview endpoint (with `base_seq`) and maps `ValidationError.path` (JSON pointer) to the matching field. No client-side JSON-Schema validator in v1.
- **Preview:** if `supports_preview`, show `PreviewResult` before apply.
- **Destructive operations:** `destructive: true` opens a confirm dialog; the apply request then sends `confirm_destructive: true`. If the server still answers `409 operation_conflict`, its warning text is shown and re-confirmed. Workspace deletion uses the same dialog with `?confirm=true`.

### 3.6 Other UI areas
- **Workspaces, import, compatibility panel:** upload with progress → job polling → compatibility report grouped by `status`, showing `preserved` / `editable` flags and `location`. The report text is displayed as given; the UI does not rewrite statuses.
- **Data Tables view + bridge:** same grid, paged table `DataSource`; dialogs for `from-range` (header row, dtype overrides, preview) and `to-sheet`.
- **Charts:** ECharts via `echarts/core` with only the needed chart types and components. `ChartSpec` + `ChartData` → ECharts options in one mapping module; RTL handled by axis inversion and Persian font family; digit formatting through the same formatters as the grid.
- **History panel:** list from `GET …/history` (cursor paging); undo/redo buttons; redo tail shown as undone.
- **Saved Tools:** list/create/run; run dialog is generated from `ToolInput[]`.
- **Export:** format picker → job → download link; export compatibility report shown the same way as the import report.

### 3.7 Security (web)
Strict CSP delivered by nginx (and by the API for its own responses): `default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'`. No inline scripts, no CDN. The one runtime risk to verify early: ECharts and any style handling must work under this CSP; if a relaxation is needed it is recorded in DECISIONS.md, not applied silently.

---

## 4. Deploy (`deploy/`)

```
deploy/
  docker-compose.yml
  .env.example                   # every setting, with safe defaults and comments
  api.Dockerfile                 # multi-stage, non-root; build context = repo root
  web.Dockerfile                 # builds static bundle, copies into the nginx image
  nginx/nginx.conf, conf.d/gridora.conf
  certs/README.md                # where certificates go; not committed
  TLS.md                         # internal CA, provided certificates, dev self-signed
  backup/backup.sh restore.sh    # + entrypoint/cron for the backup service
  scripts/smoke.sh               # post-start checks used in CI and by operators
```

- **Services:** `nginx` (TLS, static bundle, reverse proxy `/api`, security headers, CSP, `client_max_body_size`, long timeouts for upload/download, login rate-limit zone), `api`, `postgres`, `backup` (optional profile).
- **Migrations:** `api` entrypoint runs `alembic upgrade head` under a Postgres advisory lock so a second start cannot race.
- **Healthchecks:** postgres `pg_isready`; api `/healthz` (liveness) and `/readyz` (DB reachable, storage writable, engine/dataops adapter loaded); nginx a local status check. Compose `depends_on` uses `condition: service_healthy`.
- **Volumes:** `pgdata`, `dataroot` (api read-write, backup read-only), `backups`.
- **Backup:** nightly `pg_dump` (custom format) + file snapshot with `rsync --link-dest` (chosen over restic to avoid a new dependency; restic stays an option). Retention configurable. `restore.sh` restores DB and files. Because files are immutable-versioned, file restore is additive (per `ARCHITECTURE.md` §10). Restore is **documented now and verified in Phase 4**, as scheduled.
- **No outbound network at runtime:** no CDN, fonts, analytics or update checks; the runtime containers need no egress. Build-time registry access is allowed; air-gapped builds (vendored wheels/npm cache or `docker save` bundles) are a Phase 4 item and will be reported as such until verified.
- **Pinned artifacts:** lockfiles for pip and npm; base images pinned by tag now and by digest at release.
- **Runtime hardening:** non-root users, read-only root filesystem where possible, no published ports except nginx.

---

## 5. Test plan

| Layer | What | Tooling |
|---|---|---|
| Unit (api) | services, repos, storage layout, envelope/error mapping, history (undo/redo/truncate/compaction), job state machine | pytest |
| Unit (web) | geometry math (100k, 1M rows, scaling boundary), block cache LRU/cancel/dedupe, selection + RTL keyboard, input normalization, formatters (digits, Jalali), form renderer, API client | Vitest |
| Contract | route table equals `API_CONTRACTS.md`; responses validate against `gridora_contracts` models; error codes ⊆ `ERROR_CODES` | pytest (+ schemathesis once approved) |
| Isolation | OpenAPI-driven two-user matrix described in §2.4; admin cannot read user files | pytest + Postgres service |
| Session/CSRF | missing/wrong token, expired and logged-out sessions, session rotation on login, cookie flags, rate limit → 429 | pytest |
| Upload limits | exactly 100 MB passes; 100 MB + 1 byte → 413; lying `Content-Length`; wrong magic bytes → 415; non-ZIP named `.xlsx`; interrupted upload leaves no final file | pytest |
| No path leak | a test-client fixture scans **every** response body and header in the whole suite for `DATA_ROOT`, `/users/`, storage keys; any hit fails the test | pytest fixture |
| Boundaries | AST import-linter test from §2.1 | pytest |
| Stub swap | same API scenarios parametrized over `stub` and (when it exists) `real` | pytest |
| History/rehydration | live state equals state rebuilt from last save + replayed entries after cache eviction/restart | pytest |
| Jobs | claim/skip-locked, crash recovery, timeout, error mapping to `import_failed` | pytest |
| i18n | `fa`/`en` key parity; no literal UI strings; RTL screenshot snapshots of key screens; Persian fixture data (sheet names, text, digits) | Vitest, ESLint, Playwright |
| Grid performance | 100k rows × 20 columns seeded via the stub: rendered cell count stays bounded after jumping to the bottom, request count/size bounded, scroll frame time measured and recorded. Numbers are reported as measurements on stated hardware, not as budgets met | Playwright |
| E2E | Definition-of-Success flow: workspace → import → view/edit → operation → chart → save → reopen → undo/redo → save tool → export → read compatibility report | Playwright |

**Stub caveat for E2E:** while only the stub exists, XLSX import, formulas, real compatibility reporting and Data Tables cannot be exercised. Those steps will be marked skipped with the reason in the output; they will not be faked as passing.

**CI gates** (from `TESTING_STRATEGY.md`): ruff, mypy, tsc, ESLint, stylelint, unit + contract + isolation tests, license scan, Docker image build. CI workflows live in `.github/`, which is outside my folders (§10, item 10).

---

## 6. Dependencies expected (each needs a DECISIONS.md / THIRD_PARTY_NOTICES.md entry via PR)

Licenses below are my expectation and are **to be verified** in the PR that adds each dependency; none is recorded as checked yet.

| Area | Candidate | Expected license | Why / alternative |
|---|---|---|---|
| Web | react, react-dom, vite, typescript | MIT / MIT / MIT / Apache-2.0 | mainstream; named in ARCHITECTURE |
| Web | @tanstack/react-query, zustand | MIT | server vs. UI state; alt: Redux Toolkit (heavier) |
| Web | echarts | Apache-2.0 | named in ARCHITECTURE |
| Web (dev) | vitest, @playwright/test, eslint, stylelint (+ logical-properties plugin, literal-string rule) | MIT / Apache-2.0 / MIT | testing and RTL/i18n enforcement |
| Web | Persian font (Vazirmatn) | OFL (verify) | offline Persian rendering |
| Api | fastapi, pydantic-settings, uvicorn | MIT / MIT / BSD | named in ARCHITECTURE |
| Api | sqlalchemy 2, alembic, asyncpg | MIT / MIT / Apache-2.0 | named in ARCHITECTURE; async driver choice verified in PR 2 |
| Api | argon2-cffi | MIT | argon2id |
| Api | streaming multipart parser | TBD in PR 3 | enforce 100 MB without buffering |
| Api (test) | pytest, httpx, schemathesis, ruff, mypy | — | per TESTING_STRATEGY |

Deliberately **not** added: Redis/Celery, an i18n framework, a UI component framework, a JSON-Schema form library, a client-side JSON-Schema validator, a Jalali library (display uses `Intl`).

---

## 7. Risks

1. **Contract gaps** (§10) can block integration details; mitigated by working against current contracts and filing `CONTRACT_CHANGE`.
2. **Stub drift:** a stub that is more permissive than the real engine hides bugs. Mitigation: shared parametrized tests, `STUB` markers, UI badge, and stubs that return `unsupported_workbook` instead of pretending.
3. **Working-copy memory:** a 100k × 20 workbook per open document may be large; cache cap + LRU + rehydration; real numbers measured once the real engine exists.
4. **Single-process limit:** working copies live in memory, so v1 supports one API process. Documented limitation (accepted, C3.2).
   **No hostile-file process isolation in v1** (ADR-011): relies on the engine's limits; Phase 4.
5. **Custom grid complexity** (IME, RTL selection, copy/paste, accessibility): scoped cut in §3.3; canvas fallback is measurement-driven.
6. **Browser height limits** at ~1M rows: handled by scaled scrolling; limits to be measured.
7. **Delta size:** large operations produce large deltas; threshold-to-blob and the history cap handle it, but compaction needs the engine's save path to be fast.
8. **CSP vs. ECharts / fonts:** verified early in PR 6/12.
9. **No progress callback** (coarse status accepted for v1) in `OperationExecutor`: long operations show only queued/running/done.
10. **Offline builds:** runtime is offline-capable by design; air-gapped build is not verified until Phase 4.
11. **Jalali display depends on browser ICU data:** pinned in tests, noted in docs.

---

## 8. Honesty and status

- `docs/INTEGRATION_PLAN.md` rows for `apps/api`, `apps/web`, `deploy/` stay **Planned** until code lands; this PR changes only `apps/PLAN.md`.
- Nothing in this plan is claimed to work. Performance figures will be reported as measurements.
- Every implementation PR lists known limitations and updates the `apps/README.md` "what works / what doesn't" section.

---

## 9. What this PR touches

Only `apps/PLAN.md`. No contract, docs, engine, dataops or CI changes.

---

## 10. CONTRACT_CHANGE decisions (from `docs/reviews/PHASE2_REVIEW.md`) and follow-ups

| # | My request | Decision | How the plan applies it |
|---|---|---|---|
| 1 | CSRF token delivery | Accepted: `AuthResult` | §2.3, web API client keeps the token in memory |
| 2 | User management | CLI + bootstrap env; no HTTP admin endpoints | §2.3 |
| 3 | Mutating response shape | Accepted: `CellsChangedResult` | §3.3 optimistic-edit merge |
| 4 | `base_seq`, window cap | Accepted; cap 1000 × 100 | §2.8, §2.10, §3.3 |
| 5 | Entry points, storage callback | Accepted: fixed factories, `PathResolver(owner_id, table_id, version)` | §2.9 |
| 6 | Styles and number formats | Accepted as optional `FormattingEngine`; client formats using `StyleInfo.number_format` | §3.3 |
| 7 | `params_schema` vocabulary, path base | Path relative to Operation root; Agent 2 documents `x-gridora-*` | §3.5 |
| 8 | Job progress | Coarse status fine for v1 | §2.7 |
| 9 | Doc inconsistencies | Fixed by Agent 0 | — |
| 10 | CI location | Agents propose `ci/<name>.yml.proposed`; Agent 0 commits | §1 (`apps/ci/`) |
| 11 | Export `result_ref` | A `FileRecord` id | §3.6 |
| 12 | Display prefs | Client-side in v1 | §3.2 |
| 13 | Jalali library | Agent 2 decides (own implementation acceptable with independent fixtures) | §3.4 (display via `Intl`) |

Other review outcomes that touch this plan: C3.1/C3.2/C3.3 (above); `Operation.extra_targets` ownership check (§2.9); `GET /operations/i18n` (§3.5); `Q2` — v1 `filter` on a sheet outputs a new table, so the UI must show the created table (`OperationResult.output`).

**Follow-ups I will raise (not blocking PR 1–6):**
- **Large `table_to_cells` (Review Q5).** The 200,000-cell `cell_patch` cap means a big table cannot be written back to the current sheet with undo. Proposal for the "write into a new sheet" delta: a `sheet_structure` delta with `change: {kind: "create_sheet", …}` produced by the engine's `StructureEngine`, so undo removes the sheet instead of storing 2 M before/after cells. To be discussed with Agents 1 and 2 before M2 closes.
- **Error code for stub-only gaps.** I will use `unsupported_workbook` (422) for XLSX in the stub; tell me if a dedicated sub-code is preferred.
