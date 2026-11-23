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
| `packages/engine` | In progress: E1 (CSV), E3 (package layer), E4 (XLSX read), E5 (value edits, undo) merged | CI green on main; `mypy` clean here; agent reports 176 tests | Not through the API yet | XLSX export (E6) and the formula core (E7, PR on `agent0/e7-formula-core`) exist in the engine; **apps/api now returns `others` (contract 0.5.0) for cell edits, operations, undo and redo (not CI-verified locally). Contract 0.6.0 adds `Workbook.calendar`, `DateColumns` and the optional `CalendarEngine` protocol; apps/api exposes `GET /workbooks/{id}/sheets/{sheet_id}/date-columns` and `PUT /workbooks/{id}/calendar` (persisted in `meta_json`, re-applied when a working copy is rebuilt; not CI-verified locally). apps/web now has cell editing, undo/redo and `others` handling (slice 3, jsdom-tested only: not run in a real browser or on the real engine); still missing in apps/web: calendar switch, history panel, conflict banner.** Full parse of 100k x 20 takes 11 to 13 s; real Excel files untested |
| `packages/dataops` | In progress: table operations M0 to M5; contract 0.4 fixes merged | CI green on main | Fake context only | Columnar adapter exists only on the agent's disk; sheet ranges capped at 200,000 cells per write |
| `apps/api` | In progress: auth, workspaces, upload, import, stub engine/executor | CI green on main | Stub only | No history, operations, export endpoints; single worker; import in a thread (ADR-011) |
| `apps/web` | In progress: sign-in, workspaces, grid benchmark work | **CI red on main** (lint) | No | No import UI, operations, charts, history |
| `deploy/` | Implemented per Agent 3 (compose, nginx, backup/restore, runbook) | Not verified by me | Stub engine only | Never run with the real engine |
| CI | Four module workflows plus contracts | Runs on every PR | n/a | web workflow red |

## Status update (2026-11-23): steps 6, 7 and 8

- **6 (web import UI, lint)**: done; lint green; checked in a real browser against the real engine (`apps/web/e2e/real_stack.py`, 28 checks).
- **7 (hardening)**: compose defaults to the real engine and the API image installs `packages/engine` and `packages/dataops`; backup/restore drill passed on live data; 100,000-row measurements in [`LIMITS.md`](LIMITS.md) (`apps/web/e2e/perf_real.py`). **Docker images were never built here** (no daemon): the first `docker compose up --build` is still the open check.
- **8 (formula gaps)**:
  - Done: `SUBTOTAL` 101-111 skip rows hidden in the file (`hidden="1"`); formulas saved without results (openpyxl and similar) are computed at import; `mypy --strict` passes on `formula/` and `calc/` without the old relaxations (one targeted `type: ignore`).
  - Checked and already right: `MODE` (incl. `#N/A` without repeats), `SUMIF` wildcards and `<>`, `XLOOKUP` match modes and search order, common `TEXT` formats (`#,##0.00`, `%`, sections, `[>1000]`, `E+`, fractions, padding).
  - **Not done** (needs design, not a patch): spilled ranges (a dynamic-array formula writes only its top-left cell; neighbours, `#SPILL!` collisions, `A1#` and undo of cells outside the edit are missing), data tables (`TABLE()`), `GETPIVOTDATA`/cube functions (no pivot or OLAP model), web functions (`WEBSERVICE`, `FILTERXML`: refused on purpose, the engine has no network access), `SUBTOTAL` for rows hidden by an AutoFilter, and the full list of exotic number-format codes.
