# Gridora — Integration Plan & Module Status

## Phases

| Phase | Goal | Exit criteria |
|---|---|---|
| 1 | Architecture, contracts, boundaries | Docs reviewed and accepted by the owner |
| 2 | Agents plan and spike | Each agent's implementation plan reviewed; engine library spike decided (ADR-003) |
| 3 | Build and integrate | Vertical slices integrated: open → edit → operate → chart → save → export |
| 4 | Harden and ship | `docker compose up` works on a clean machine; backup/restore verified; limitations documented |

Each phase ships `docs/phases/PHASE-N.md` describing real, verified functionality.

## Integration slices (Phase 3 order)

1. Upload CSV → grid display (stub engine allowed).
2. XLSX import with compatibility report.
3. Cell edit + undo/redo.
4. First operations (sort/filter/dedupe) with preview.
5. Data Tables + bridge.
6. Charts.
7. Save versions + export.
8. Saved Tools/workflows.

## Review gate for every merge

- Contract conformance (schema tests).
- Tests written and passing in CI.
- No cross-module imports against the rules.
- Docs and status table updated.
- Honest limitations noted.

## Module status

Legend: Planned · In progress · Implemented · Tested · Integrated.
"Verified by Agent 0" means I ran it myself. The review sandbox has no network, so Python packages that need `polars`, `fastapi` or `sqlalchemy`, and the web app, could **not** be run by me; their test results are the agents' claims until CI runs.

| Module | Status | Verified by Agent 0 | Integrated | Known limitations |
|---|---|---|---|---|
| Architecture & contract docs | Implemented | Read | n/a | CC decisions recorded in `docs/reviews/` |
| `contracts/` v0.3.0 | Tested | 13 tests pass; TS strict typecheck passes | No | Self-consistency only; no JSON Schema export |
| `packages/engine` | In progress (E1: CSV import/export, cell store) | 64 engine tests pass, `mypy --strict` clean | With `apps/api` through the stub-swap factory only | **No XLSX import/export, no edits, no formulas yet.** XLSX open cost unmeasured (probe: ~6 s lower bound for an eager parse) |
| `packages/dataops` | In progress (M0–M5 implemented per Agent 2) | Not run (no polars offline) | Not yet against the real engine | No 100k benchmark through the executor yet; join cannot be a pipeline step; README has stale lines |
| `apps/api` | In progress (PR 1–5) | Not run (no fastapi/Postgres offline) | Stub engine/executor only | No history/undo, no operations endpoints, no export; single worker; import in a thread (ADR-011) |
| `apps/web` | In progress (PR 6: sign-in, workspaces) | Not run (no npm install offline) | No | No grid, import, operations, charts; jsdom tests only |
| `deploy/` | **Planned** | — | — | Not started; it was due before PR 8 (PHASE2_REVIEW C3.3) |
| CI | Workflows committed for engine, dataops, apps-api, apps-web | YAML parses | — | **Never run yet**; first run may need fixes |
