# Roadmap and module status

Last updated 2026-11-24. This file is the single place that says what is done, what is verified and what remains. Details of what each module does: [REFERENCE.md](REFERENCE.md); measured limits: [LIMITS.md](LIMITS.md).

## Status by module

| Module | State | Evidence |
|---|---|---|
| `contracts/` | In use by every module, Python and TypeScript mirrored | contract tests in CI |
| `packages/engine` | CSV and XLSX import (lazy), edits with undo deltas, columnar access, range snapshots, formulas (about 400 functions, spill, calendars), XLSX/CSV export | unit tests, corpus tests on 31 real files and 18 hostile files, replay-determinism tests; CI green |
| `packages/dataops` | 15 operations, preview with effect summary, pipelines, saved tools, Data Tables (Parquet versions), chart data, Persian search, executable integration guide | ~480 tests; CI green |
| `apps/api` | Auth, workspaces, upload, jobs, windows, edits, undo/redo, operations, Data Tables with history, charts, tools, save, export; real engine and dataops wired | ~260 tests on stub and real engine; CI green |
| `apps/web` | Sign-in, workspaces, import with compatibility panel, virtualized RTL grid, editing, copy/paste, undo/redo, history panel, conflict banner | unit and component tests; real-browser scripts in `apps/web/e2e` (Firefox, Chromium) |
| `deploy/` | Compose stack with real engine, backup and restore, TLS guide, runbook | smoke, backup and restore scripts; `deploy-stack` workflow builds and exercises the stack |

## Remaining work that does not need the owner

Everything here can be built and tested with automated checks (unit tests, API tests, scripted browser runs, benchmarks).

### Interface
1. **Done (PR #73):** **Task bar and operation panel** ([UX_SPEC.md](UX_SPEC.md) §3–§5): search by Persian task phrases (`search_operations`), selection-aware suggestions, form generated from `params_schema`, live preview with effect-stating Apply button, toast with Undo, the "convert to Data Table" offer for `too_large_for_history` (F3, F4).
2. **Screens for Data Tables, charts and saved tools** (F5, F7) and for save/export with the export report (F6). The API for all of them exists.
3. **Find** (Ctrl+F), frozen panes, fill handle, formatted clipboard. (Column resize is done: drag a header border, not saved yet.)
4. **Cell styles and number formats in the grid**: implement `FormattingEngine` in the engine (styles are preserved but not exposed) and render them.
5. **Paste fidelity**: shift relative references in pasted formulas; convert pasted date text to dates.
6. **Keyboard help**, density setting, dark theme check, automated accessibility checks (axe) in the scripted browser run.
7. **Cross-browser scripted checks** (Chromium and WebKit besides Firefox) and moving the real-stack browser script into CI.

### Engine
8. `SUBTOTAL` for rows hidden by an AutoFilter; `A1#` spill references; implicit-intersection removal for bare ranges.
9. Faster export after a bulk write (22 s for 100,000 rows) and progress/cancel for long engine calls (design in `packages/engine/DESIGN.md` §0.8).
10. Row/column insert and delete (`StructureEngine`) — the riskiest feature; needs reference rewriting and its own test plan.
11. Process-level import isolation (snapshot profile W, ADR-011/015) so hostile parsing cannot take the API down.
12. Shared and array formula member cells are read-only today; make them editable.

### Dataops and API
13. `suggest()` (column profile → recommended operations) per `packages/dataops/docs/SUGGESTIONS.md` — the design has open questions listed in its §8 that the owner must settle first (see below).
14. Columnar methods in the API context so large sheet ranges take the fast path.
15. Pagination for list endpoints; progress for jobs; cancelling a running import.

### Quality, security, operations
16. **Done:** split the slow corpus tests into their own CI job (the engine suite takes about 90 s).
17. **Done except image digests:** dependency and licence scan in CI (informational `supply-chain` workflow) (`pip-licenses`, `license-checker`, `pip-audit`, `npm audit`) and pinning container base images by digest.
18. More hostile-file fuzzing for the package layer and formula parser; resource-limit tests on the import worker.
19. **Done:** documentation: `docs/ADMIN_GUIDE.md` (install, upgrade, backup, restore, TLS, logs, user management) and `docs/USER_GUIDE.fa.md` (Persian user guide). Both can be written from the running behaviour.
20. Performance work from [LIMITS.md](LIMITS.md): memory per formula cell (8–12 KB), first recalculation of large imports (13 s for 200,000 formulas).
21. Remaining formula gaps: `TABLE()` data tables, `GETPIVOTDATA` and cube functions (no pivot or OLAP model), exotic number-format codes.

## Remaining work that needs the owner

| Item | Why it needs you |
|---|---|
| Run `docker compose up --build` on a real machine and report any error | The CI workflow covers it, but only a real install proves the guide works |
| Hands-on test of the interface with real Persian files, following [UX_SPEC.md](UX_SPEC.md) §12; write findings in `docs/UX_TEST_1.md` | Judging layout, wording and speed is yours |
| Open exported `.xlsx` files in real Excel and report any repair prompt | Only Excel itself is the oracle; LibreOffice is secondary |
| A real Persian workbook with right-to-left sheet view and a real 100,000-row Excel file | The corpus has an Arabic RTL workbook and synthetic large files only |
| Decide terminology: «خانه» or «سلول» for a cell, «محدوده» for a range (list in [I18N_SPEC.md](I18N_SPEC.md)) | Product wording |
| Decide the open questions in `SUGGESTIONS.md` §8 (automatic or on click, thresholds, remembering "dismiss") | Product behaviour |
| Decide Jalali input: date picker in cells, or display conversion only | Product behaviour |
| Test with a screen reader; test Safari and Chrome by hand | Needs real assistive technology and devices |
| Rotate the GitHub App private key that was pasted in chat, and remove the App's access when development ends | Account security |

## Verification rules
A feature is "supported" only when a test proves it. The corpus manifest (`corpus/manifest.json`) and the engine's compatibility registry are the record of what was checked; Excel itself has not been used as an oracle yet.
