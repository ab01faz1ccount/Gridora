# Phase 1 — Architecture & Contracts

**Status:** Done, owner decisions applied. **No product features are implemented in this phase.**

## What this phase delivers

Documents: architecture, requirements, data model, API contracts, module boundaries, integration plan, compatibility strategy, security model, testing strategy, decision records, third-party notices.

Also machine-readable contracts in `contracts/` (Python and TypeScript), agent briefs, working agreement, review checklist, Persian/RTL spec, operations catalog and engine spike plan. These were added with Phase 2 preparation.

## What Gridora will do (planned feature catalogue)

This list is the target for later phases. Status is *Planned* unless stated.

| Area | Capability | Phase | Status |
|---|---|---|---|
| Workspace | Private workspace and files per user | 3 | Planned |
| Import | XLSX and CSV import with a compatibility report | 3 | Planned |
| Grid | Virtualized spreadsheet view and cell editing (up to ~100k rows) | 3 | Planned |
| Operations | Sort, filter, remove duplicates, find/replace, fill, split/merge columns, group & aggregate, pivot, join, computed columns — all through forms, with preview | 3 | Planned |
| Data Tables | Structured tables, convert sheet ranges ↔ tables | 3 | Planned |
| Charts | Bar, line, pie, scatter, area (ECharts) | 3 | Planned |
| History | Undo/redo and an operation history panel | 3 | Planned |
| Workflows | Save a sequence of operations as a reusable tool | 3 | Planned |
| Save/Export | Versioned saves (original never overwritten); XLSX and CSV export | 3 | Planned |
| Compatibility | Per-file report: supported / partial / preserved / unsupported | 3 | Planned |
| Deployment | Docker Compose + Nginx, backup script | 4 | Planned |

## Key decisions (all proposed, see DECISIONS.md)

Modular monolith; interface-first modules; own OOXML preservation layer with a formula backend chosen by a Phase 2 spike; server-authoritative workbooks with windowed transport; operations with inverse deltas for history; Parquet-backed Data Tables.

## Research findings so far

README/registry-level only, not code audits. IronCalc looks like the most relevant engine candidate; GridCraft is a young alpha app with ambitious claims to be verified; Gridline is a terminal spreadsheet, likely idea-source only. See COMPATIBILITY_STRATEGY.md.

## Limitations of this phase

No code, no tests, no verified compatibility claims. Library licenses were taken from READMEs/crate metadata and must be re-checked in the repositories before any reuse.

## Owner decisions

1. UI: Persian-first with RTL from the start.
2. Auth: local accounts only in v1.
3. Max upload size: 100 MB.

## Next

Phase 2: push the repo, hand each agent its brief from `agents/`, review their plans, run the engine spike. See [PHASE-2.md](PHASE-2.md).
