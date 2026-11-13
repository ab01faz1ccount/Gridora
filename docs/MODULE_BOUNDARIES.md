# Gridora — Module Boundaries & Agent Briefs

Status: Phase 1 draft. Briefs are handed to the specialist agents in Phase 2 after owner review.

## Dependency rules

```
apps/web ──HTTP──> apps/api ──> packages/engine
                         └────> packages/dataops
contracts/  ← imported by all, imports nothing
```
- `engine` ⟂ `dataops`: no imports between them.
- Only `apps/api` composes modules. Only Agent 0 changes `contracts/`; others propose changes via a `CONTRACT_CHANGE` note in their PR.
- No module reads/writes another module's storage directly.

## Agent 1 — Workbook Engine & Excel Compatibility (`packages/engine`)

**Scope:** Workbook/Sheet model; XLSX/CSV import and export; OOXML package layer that preserves unknown parts and relationships; cell edits and deltas; formula evaluation (via spike-selected approach); compatibility reporting; engine fixtures corpus.

**Deliverables:** `WorkbookEngine` implementation; compatibility feature registry (stable codes); round-trip test corpus; benchmark script (100k rows); a written spike report on candidate libraries (IronCalc, GridCraft, Gridline, others) with license verdicts and provenance entries.

**Depends on:** `contracts/`. Nothing else.

**Acceptance:** import → edit → export round-trips the fixture corpus with every unsupported/lossy item reported; unknown parts byte-preserved; hostile-input tests pass (zip bomb, XXE, huge sheet dimension); no claim of full compatibility.

**Must not modify:** `apps/*`, `packages/dataops`, `contracts/` (propose only), DB schema.

## Agent 2 — Data Operations & Analytics (`packages/dataops`)

**Scope:** operation registry and executor; initial operations (sort, filter, remove duplicates, find/replace, fill down/up, trim/case, split/merge columns, group & aggregate, pivot, join, computed column from a GUI expression builder, type conversion); pipelines; reusable Tools; Data Table store (Polars + Parquet versions, DuckDB for joins/SQL where useful); sheet↔table bridge; chart data aggregation.

**Deliverables:** `OperationExecutor`, `TableStore`; param JSON Schema per operation; preview support; inverse deltas; unit tests with Polars fixtures; performance test at 100k rows.

**Depends on:** `contracts/`; reads/writes sheet ranges only through the `ExecContext` interface.

**Acceptance:** every operation has validate/preview/apply/undo tests; destructive flag set correctly; results deterministic; no import of `engine`.

**Must not modify:** `packages/engine`, `apps/*`, `contracts/`.

## Agent 3 — Frontend, Backend & Platform (`apps/web`, `apps/api`, `deploy/`)

**Scope:** FastAPI app implementing API_CONTRACTS; auth, workspaces, file storage layout, jobs, history service, Postgres schema/migrations; React/TS grid UI, operation forms generated from `OperationDescriptor`, chart UI, history panel, compatibility panel; Docker/Nginx/compose; backup script.

**Deliverables:** running stack via `docker compose up`; OpenAPI matching contracts; UI for every item in the Definition of Success; stub implementations of `WorkbookEngine`/`OperationExecutor` for early development (to be replaced by real modules).

**Depends on:** `contracts/`; real engine/dataops at integration time.

**Acceptance:** user isolation tests; CSRF/session tests; large-window grid scroll at 100k rows; upload limits enforced; no internal paths in any response.

**Must not modify:** `packages/engine`, `packages/dataops`, `contracts/`.

## Cross-cutting rules for all agents

- Small PRs, one concern each, with tests and a docs update. Update the module status table in INTEGRATION_PLAN.md.
- No new dependency without an entry in DECISIONS.md (why, alternatives, license).
- Copying external code requires a license check and a THIRD_PARTY_NOTICES + provenance entry first.
- Each phase ends with an updated `docs/phases/PHASE-N.md` describing what actually works.
