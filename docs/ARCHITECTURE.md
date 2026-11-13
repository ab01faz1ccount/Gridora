# Gridora — Architecture

Status: **Phase 1 draft, pending review.** Nothing described here is implemented yet.

## 1. System boundaries

Gridora is a self-hosted, browser-based spreadsheet and data platform. It runs entirely inside the customer's network.

- **Inside the boundary:** web UI, API, workbook engine, data operations, PostgreSQL, file storage, Nginx.
- **Outside the boundary:** nothing is required. No outbound calls are made with user data. Package registries are used only at build time.
- **Out of scope for now:** AI features, real-time collaboration, hosted SaaS dependencies, microservices.

## 2. Shape: modular monolith

One deployable backend process (FastAPI) that imports two internal Python packages. Modules communicate through typed Python interfaces, not over the network. Each package can later be extracted to a separate process without changing its interface (see ADR-002).

```
 Browser (React + TS + ECharts)
        │  HTTPS, JSON (REST /api/v1)
      Nginx  ── static web bundle
        │
   FastAPI app  (apps/api)         ← Agent 3
     ├── auth, workspaces, files, jobs, history service
     ├── imports  gridora_engine   ← Agent 1  (workbook model, OOXML I/O, formulas)
     ├── imports  gridora_dataops  ← Agent 2  (operations, pipelines, Data Tables)
     │
   PostgreSQL (metadata)     File storage (originals, generated, Parquet)
```

## 3. Core modules

| Module | Owner | Responsibility | Owns data |
|---|---|---|---|
| `apps/web` | Agent 3 | Grid UI, toolbars, operation forms, charts, history panel | UI state only |
| `apps/api` | Agent 3 | HTTP API, auth, workspaces, job runner, persistence, orchestration | Postgres metadata, file layout |
| `packages/engine` | Agent 1 | Workbook/Sheet model, XLSX import/export, OOXML package preservation, formula evaluation, compatibility report | In-memory workbook model; OOXML parts |
| `packages/dataops` | Agent 2 | Operation registry, pipeline execution, Data Tables (Polars/DuckDB), sheet↔table bridge, chart data aggregation | Data Table contents (Parquet) |
| `contracts/` | Agent 0 | JSON Schemas and generated types shared by all modules | Nothing |

Rules: `engine` and `dataops` never import each other and never import `apps/api`. The API layer is the only place that wires them together. Shared types live only in `contracts/`.

## 4. Data ownership

- **Postgres** owns: users, sessions, workspaces, file records, workbook/table metadata, history entries, saved tools/workflows, chart specs, jobs.
- **File storage** owns: original uploads (immutable), saved workbook versions (XLSX), Data Table versions (Parquet).
- **Workbook working copy:** the API loads a workbook into the engine on open and keeps it in a per-session cache. The authoritative state is the last saved version plus the history log.
- A fact has exactly one owner. Anything else is a cache.

## 5. Communication

- Browser ↔ API: REST + JSON; long tasks return a `job_id` and are polled (SSE may be added later).
- API ↔ engine/dataops: direct function calls with the contract types.
- Large cell ranges are fetched by **viewport window** (rows/cols range), never as a whole sheet. Windowing only limits what the browser *loads and renders*; editing is unaffected. The user edits any visible cell normally, the browser sends the edit to the server, the server applies it (and recalculates), and returns the changed cells. The browser prefetches neighboring windows while scrolling and keeps recently viewed windows cached, with pending edits shown optimistically.

## 6. File-processing lifecycle

1. **Upload** → size/type check → stream to quarantine path → hash.
2. **Scan** → structural validation (zip limits, XML limits, part allowlist for parsing). Original stored immutable.
3. **Import** (job) → engine builds the Workbook model, preserving unknown parts verbatim → produces a `CompatibilityReport`.
4. **Edit** → every change goes through an Operation (or a cell edit, itself an operation) → history entry with inverse delta.
5. **Save** → write a *new version* of the workbook file; the original is never overwritten. Atomic rename after fsync.
6. **Export** → engine writes XLSX/CSV; report lists anything not round-tripped.

## 7. Authentication and authorization

- Local accounts, passwords hashed with argon2id, server-side sessions in an HttpOnly cookie, CSRF token on mutating requests.
- Every row and file record carries `owner_id`; every query is scoped by the authenticated user. No cross-user sharing in v1.
- Roles: `user`, `admin` (user management, backup settings only; admins cannot read other users' files through the API).
- LDAP/OIDC is a possible later extension, behind the same session interface.

## 8. Persistence

- Postgres via SQLAlchemy 2 + Alembic migrations.
- Files under `${DATA_ROOT}/users/<user_uuid>/…`, addressed by opaque UUID. Clients never see paths.
- Data Tables: Parquet files, versioned immutably; metadata in Postgres. DuckDB queries Parquet directly.

## 9. Error handling

Single error envelope (see API_CONTRACTS). Domain modules raise typed exceptions with stable `code` strings; the API maps them to HTTP status codes. No stack traces to clients. Every response carries a `request_id` logged server-side.

## 10. Backup and recovery

- Nightly `pg_dump` plus file-storage snapshot (rsync/restic) via a documented script and compose service.
- Restore procedure documented and tested in Phase 4. Because files are immutable-versioned, file restore is additive.

## 11. Deployment

Docker Compose: `nginx`, `api`, `postgres`, optional `backup`. One `.env`. No external network required at runtime. Build artifacts are pinned (lockfiles) for offline-capable builds.

## 12. Major dependency justification

| Dependency | Why | Alternative considered |
|---|---|---|
| React + TypeScript | Mainstream, strong typing for contracts | — |
| Custom grid component | Needs spreadsheet-specific behavior (selection, fill handle, virtualization at 100k rows) | Off-the-shelf grids lack Excel-style behavior or have restrictive licenses |
| Apache ECharts | Chart variety, offline, Apache-2.0 | — |
| FastAPI | Typed, async, OpenAPI for free | — |
| PostgreSQL | Metadata integrity, concurrent users | SQLite (rejected: multi-user server) |
| Polars | Fast columnar ops at 100k rows+ | pandas (slower, heavier memory) |
| DuckDB | SQL over Parquet for joins/aggregates and a future SQL builder | Only used where Polars is awkward |
| NumPy/SciPy | Only if a stats operation needs them; not a default dependency | — |

## 13. Spreadsheet engine strategy

See ADR-003 and COMPATIBILITY_STRATEGY. Summary: the engine is hidden behind a `WorkbookEngine` interface; an OOXML package layer we control preserves unknown parts; formula evaluation may be backed by an evaluated candidate library after a time-boxed spike in Phase 2. No Rust/PyO3 until a benchmark shows a need.
