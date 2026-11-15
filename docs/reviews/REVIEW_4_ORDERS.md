# Review 4 — E5 merged, state of main (2026-11-15) and orders

## State of main (checked on GitHub, not run locally except contracts and engine mypy)
- Merged: engine E3, E4, E5 (+ E5b design), dataops contracts-0.4 fixes, API stub performance work, tool pinning.
- CI on main: contracts, engine, dataops, apps-api **green**. **apps-web red** (one ESLint error `no-useless-assignment`, `apps/web`, line 36, from the pinned lint version); Agent 3 owns the fix.
- Folder ownership and import boundaries: still clean.
- Still not running anywhere: an end-to-end flow (upload to grid to edit to undo). Nothing has been tested through the real engine from the API yet.

## Decisions (ADR-015, contract 0.4.1)
1. **CC-12 accepted**: optional `ColumnarEngine` protocol (`read_range_columnar`, `write_range_columnar`).
2. **History size error**: top-level `operation_conflict` (409) with detail code `too_large_for_history`. The engine must use this too (it used `validation_failed` + reason).
3. **Order of engine work**: E6 export -> E5b-1 columnar -> E5b-2 snapshot deltas (profile R only). Profile W (whole workbook, import isolation) waits for Phase 4.
4. **Whole-sheet work is a job with progress.** Agent 1 proposes the progress/cancel hook (CC-13).
5. **ADR-003 part 2 stays pending; E7 stays blocked.** Gate: E6 merged and real Excel files measured; if a real 100k x 20 file needs more than 30 s to parse in pure Python, the Rust-core option returns for a decision before any formula work.

## Orders

### Agent 1 (engine)
1. Merge hygiene: rebase on main (contracts 0.4.1).
2. **E6 export** as planned (patch edited rows into the original sheet XML, consume `dirty_rows`, unknown parts byte-equal, hostile-file tests, export `CompatibilityReport`). The report must say that formula results are **not recalculated** after edits and list formula cells whose cached values may be stale. Never write a file you cannot re-open with your own reader in a test.
3. Change the history-cap error to `too_large_for_history` raised as the engine's typed error that apps/api already maps to `operation_conflict`; update tests and README.
4. Then **E5b-1** (implement `ColumnarEngine`, equivalence tests against `get_cells`/edits, measured against the 7.8 microsecond figure), then **E5b-2**.
5. Write CC-13 as a short proposal: how a long call (full parse, columnar read of a whole sheet) reports progress and can be cancelled, in a way that works from a worker thread. Do not build it before Agent 0 answers.
6. Do not start E7. Keep the SPIKE_REPORT open items current; add the full-parse time of every real Excel file you receive.
7. Shared and array formula children stay non-editable with a typed error until E7; put the exact error code in the README.

### Agent 2 (dataops; the usage limit is the problem)
1. **First thing when you resume: commit and push the unpushed columnar work to a branch `agent2/columnar-wip` and open a draft PR**, even if BENCHMARKS.md and README are not updated. Unpushed work on a disk that can disappear is the largest risk right now.
2. The columnar adapter keeps using your fake context; the real `ColumnarEngine` arrives only with E5b. Do not wait for it.
3. Everything else in Review 3 orders stands (both paths must give identical results and identical undo; re-measure; honest numbers; in-memory pipeline hand-off only if per-step undo stays exact).
4. Raise `too_large_for_history` exactly as the API expects (`operation_conflict` with that detail code).

### Agent 3 (platform)
1. **Fix the apps-web ESLint error first** so main is green.
2. Finish the current PR; then **PR 7 grid** and **PR 8 import** as ordered.
3. **Wire the real engine** behind the existing factory flag (`GRIDORA_ENGINE=real`): CSV and XLSX upload, window reads, cell edits with undo, through the API. Add an integration test that runs the real engine (no stub) for upload -> window -> edit -> undo. This is the first true end-to-end slice; report what fails.
4. Map `operation_conflict` + `too_large_for_history` to a clear Persian message that offers "convert this range to a Data Table".
5. Whole-sheet operations: run as `operation` jobs with progress (use the job runner you built); do not hold a request open for 10+ seconds.
6. Implement `ColumnarExecContext` on top of the engine only when `isinstance(engine, ColumnarEngine)`; otherwise keep the cell path.
