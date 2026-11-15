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

## Module status (updated 2026-11-15)

Legend: Planned · In progress · Implemented · Tested · Integrated. "Verified by Agent 0" means I ran it; otherwise the source is GitHub CI or the agent's report.

| Module | Status | Evidence | Integrated | Known limitations |
|---|---|---|---|---|
| Architecture & contract docs | Implemented | Read | n/a | ADR-001 to ADR-015 |
| `contracts/` v0.4.1 | Tested | 17 tests pass here; TS strict typecheck passes | No | Self-consistency only |
| `packages/engine` | In progress: E1 (CSV), E3 (package layer), E4 (XLSX read), E5 (value edits, undo) merged | CI green on main; `mypy` clean here; agent reports 176 tests | Not through the API yet | **No XLSX export (E6), no formulas (E7); formula results are not recalculated after edits.** Full parse of 100k x 20 takes 11 to 13 s; real Excel files untested |
| `packages/dataops` | In progress: table operations M0 to M5; contract 0.4 fixes merged | CI green on main | Fake context only | Columnar adapter exists only on the agent's disk; sheet ranges capped at 200,000 cells per write |
| `apps/api` | In progress: auth, workspaces, upload, import, stub engine/executor | CI green on main | Stub only | No history, operations, export endpoints; single worker; import in a thread (ADR-011) |
| `apps/web` | In progress: sign-in, workspaces, grid benchmark work | **CI red on main** (lint) | No | No import UI, operations, charts, history |
| `deploy/` | Implemented per Agent 3 (compose, nginx, backup/restore, runbook) | Not verified by me | Stub engine only | Never run with the real engine |
| CI | Four module workflows plus contracts | Runs on every PR | n/a | web workflow red |
