# Phase 3 — Build & Integrate

**Status:** Planned. This README is the template that Agent 0 completes with verified facts when the phase finishes; every capability below is **Planned** until the module status table in `docs/INTEGRATION_PLAN.md` says otherwise.

## Goal
Produce a working vertical slice of the Definition of Success: workspace → import → view/edit → operate → chart → save/reopen → undo/redo → save tool → export → compatibility report.

## Integration slices (in order)
1. CSV upload → grid display (stub engine allowed).
2. XLSX import with compatibility report.
3. Cell edit with undo/redo.
4. First operations (sort, filter, remove duplicates) with preview and destructive confirmation.
5. Data Tables and the sheet↔table bridge.
6. Charts.
7. Versioned save and export.
8. Saved Tools (reusable workflows).
9. Remaining operations from `docs/OPERATIONS_CATALOG.md`.

## Feature table (filled in at phase end)

| Feature | Status | Verified by | Known limitations |
|---|---|---|---|
| Workspaces | Planned | — | — |
| CSV/XLSX import | Planned | — | — |
| Grid view/edit | Planned | — | — |
| Operations (GUI) | Planned | — | — |
| Data Tables + bridge | Planned | — | — |
| Charts | Planned | — | — |
| Undo/redo + history | Planned | — | — |
| Saved tools | Planned | — | — |
| Save/export | Planned | — | — |
| Compatibility report | Planned | — | — |
| Persian/RTL UI | Planned | — | — |

Statuses allowed: Planned · Partial · Working. "Working" requires a passing test or a recorded manual check.

## Exit criteria
- Playwright scenario of the full Definition-of-Success flow passes against the real engine and dataops (not stubs).
- Security isolation tests pass; hostile-file tests pass.
- 100k-row benchmark numbers recorded in the module `BENCHMARKS.md` files.
- Every module README states what does and does not work.
