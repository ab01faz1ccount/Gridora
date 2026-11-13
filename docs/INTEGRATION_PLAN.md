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

Legend: Planned · In progress · Implemented · Tested · Integrated

| Module | Status | Tested | Integrated | Known limitations |
|---|---|---|---|---|
| Architecture & contract docs | Implemented | n/a | n/a | Owner decisions applied; agents may raise CONTRACT_CHANGE |
| `contracts/` (pydantic + TypeScript) | Tested | 8 smoke tests pass; TS strict typecheck passes | No | Proves self-consistency only; no module implements it yet. No JSON Schema export yet |
| `packages/engine` | Planned | — | — | Library choice pending spike |
| `packages/dataops` | Planned | — | — | — |
| `apps/api` | Planned | — | — | — |
| `apps/web` | Planned | — | — | — |
| `deploy/` (Docker, Nginx, backup) | Planned | — | — | — |
