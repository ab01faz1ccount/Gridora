# Agent 3 — Frontend, Backend & Platform

You work in `apps/web/`, `apps/api/` and `deploy/`. Read first: `docs/ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/SECURITY_MODEL.md`, `docs/MODULE_BOUNDARIES.md`, `docs/I18N_SPEC.md`, `contracts/`, `docs/WORKFLOW.md`.

## Mission
Deliver the product people actually touch: a Persian-first (RTL) browser UI, a secure API, and a one-command self-hosted deployment.

## Step 0 — Plan first (no code yet)
Submit `apps/PLAN.md`: frontend structure (state management, grid virtualization approach), backend layout, DB schema, job runner choice, i18n approach, deploy layout, test plan. Wait for Agent 0 approval.

## Deliverables
1. **Backend (`apps/api`)**: FastAPI implementing `docs/API_CONTRACTS.md` exactly (envelope, error codes, CSRF, sessions). Local accounts with argon2id. Workspaces, file storage layout (UUID paths, never exposed), upload limit 100 MB, jobs, history service (undo/redo via deltas), versioned saves (originals immutable), Postgres schema with Alembic migrations, audit log.
2. **Composition layer**: the only place that wires `WorkbookEngine`, `OperationExecutor` and `ExecContext`. Ship **stub implementations** of both protocols (in-memory, CSV only) so UI work can start before the real modules land; mark them clearly and make swapping one config line.
3. **Frontend (`apps/web`)**: React + TypeScript. Custom virtualized grid (windowed fetch, optimistic edits, keyboard navigation, selection, fill handle later), RTL-first layout using logical CSS properties, i18n catalog with Persian default and English fallback, Persian digits display option, Jalali date display option.
4. UI for each Definition-of-Success item: workspace management, import with compatibility panel, grid editing, operation panels generated from `OperationDescriptor` (with preview and destructive-confirm dialogs), Data Tables view and bridge, ECharts chart builder, history panel with undo/redo, saved Tools, export.
5. **Deploy (`deploy/`)**: Docker Compose (nginx, api, postgres, backup), `.env.example`, TLS notes, backup/restore scripts, healthchecks. Works with no outbound network at runtime.
6. Tests: user-isolation, CSRF/session, upload limits, no-path-leak, grid windowing at 100k rows, Playwright smoke test of the Definition-of-Success flow.

## Acceptance criteria
- `docker compose up` brings up a working stack on a clean machine.
- OpenAPI output validates against the contracts; responses use the standard envelope.
- Another user's resources always return `404`; no internal paths in any response.
- UI is fully usable in RTL; no hard-coded strings outside the i18n catalog.
- Stubs are replaceable by the real engine/dataops without UI changes.

## Must not modify
`contracts/`, `packages/engine/`, `packages/dataops/`, `docs/` (except module docs under your own folders).
