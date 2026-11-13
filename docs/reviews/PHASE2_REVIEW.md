# Phase 2 — Agent 0 Review of the Three Plans

Reviewed: `packages/engine/PLAN.md`, `packages/dataops/PLAN.md`, `apps/PLAN.md` (commit 62be42a).
Method: read all three in full and checked them against the boundary rules, security model, and each other. Nothing was executed; there is no code yet.

## Verdicts

| Agent | Verdict | Meaning |
|---|---|---|
| Agent 1 (engine) | **Approved with conditions** | May start E0, E1 and the spike now. Conditions C1.1 to C1.4 below. |
| Agent 2 (dataops) | **Approved with conditions** | May start M0 now. Conditions C2.1 to C2.3 below. |
| Agent 3 (platform) | **Approved with conditions** | May start PR 1 to PR 6 now. Conditions C3.1 to C3.3 below. |

All three plans respect the folder limits, ban unreviewed copying, and state honestly that nothing works yet. The contract gaps they found are real. Contracts are now **v0.2.0** (`contracts/`, ADR-010); **rebase on it before writing code**.

## Decisions on every CONTRACT_CHANGE

| Source | Request | Decision |
|---|---|---|
| A1 CC-1 | `file_id` kwarg on imports | **Accepted** |
| A1 CC-2 | `close(wb)` | **Accepted**; handles are not thread-safe |
| A1 CC-3 | styles and sheet layout access | **Accepted as optional `FormattingEngine`** (not needed before slice 3) |
| A1 CC-4 | delta includes recalculated dependents; `apply_delta` does not recalc | **Accepted, normative** |
| A1 CC-5 | structure operations | **Accepted as optional `StructureEngine`**, scheduled after E8. Shape of `change` is reviewed before implementation |
| A1 CC-6 | CSV report in `Workbook.compat`; `infer_types` option | **Accepted** |
| A1 CC-7 | more error values | **Accepted: `#SPILL!`, `#CALC!`, `#GETTING_DATA`.** Anything else maps to `#VALUE!` with a report item (original preserved) |
| A1 CC-8 | engine `reason` in `ErrorDetail.code` | **Accepted** |
| A2 #1 | `validate(op, ctx?)` | **Accepted** |
| A2 #2 | `read_page` and `table_to_cells` get `version`; `restore_version` is a pointer swap | **Accepted** |
| A2 #3 | "table created" delta | **Accepted: `from_version=0`** |
| A2 #4 | `chart_data`, `validate_tool`, `bind_tool` | **Accepted** on `OperationExecutor` |
| A2 #5 | typed `read_range`, `workspace_id`, clearing cells | **Accepted.** `read_range` returns `Cell | None`; `write_range` writes values only, uncovered cells in the range are cleared |
| A2 #6 | `PipelineStep` shape | **Flat `models.py` is normative**; docs fixed. `{"$input": name}` documented |
| A2 #7 | second table for `join` | **Changed:** use the new `Operation.extra_targets`, not `params`, so the API verifies ownership generically |
| A2 #8 | i18n catalog split | **Accepted.** Dataops ships `fa.json`/`en.json` and `catalog(locale)`; API serves it at `GET /operations/i18n` |
| A3 #1 | CSRF token delivery | **Accepted:** `AuthResult` from login and `/auth/me` |
| A3 #2 | user management | **CLI plus bootstrap env in v1.** No HTTP admin endpoints |
| A3 #3 | mutating response shape | **Accepted:** `CellsChangedResult` |
| A3 #4 | `base_seq` and window cap | **Accepted;** cap is **1000 x 100** (contract updated from 2000 x 200) |
| A3 #5 | real-module entry points, storage callback | **Accepted:** fixed factory functions and `PathResolver(owner_id, table_id, version)` (see `protocols.py`) |
| A3 #6 | styles and number formats | **Accepted** via `FormattingEngine`. For v1 the client formats using `StyleInfo.number_format`; the engine does not render text |
| A3 #7 | `params_schema` vocabulary, `path` base | **`path` is relative to the Operation root** (`/params/column`). Vocabulary: Agent 2 documents the `x-gridora-*` keywords in `packages/dataops/docs/PARAMS_SCHEMA.md`; Agent 3 renders that subset and shows a clear "unsupported field" fallback |
| A3 #8 | job progress | Coarse status is fine for v1 |
| A3 #9 | doc inconsistencies | **Fixed** in `DATA_MODEL.md` and `API_CONTRACTS.md` |
| A3 #10 | CI location | Agents propose `ci/<name>.yml.proposed`; Agent 0 commits workflows (`docs/WORKFLOW.md`) |
| A3 #11 | export `result_ref` | **A `FileRecord` id** |
| A3 #12 | display prefs | Client-side in v1 |
| A3 #13 | Jalali library | Agent 2 decides via DECISIONS (see Q6) |

## Decisions on open questions

| Q | Decision |
|---|---|
| A1-1 spike timebox | **3 working days, hard stop**, in the proposed order |
| A1-2 working assumption | Accepted, **with the performance gate C1.1** |
| A1-3 real Excel files | **Owner must supply them** (see "Needed from the owner") |
| A1-4 limits | Start with: 100:1 max compression ratio, 500 MB total uncompressed, **5 M non-empty cells** (a 100k x 20 sheet is 2 M). Tune after the E1 benchmark |
| A1-5 CSV formula injection | **Default on for text cells** starting with `= + - @`; numeric cells are never touched; option to turn off; always reported |
| A1-6 `.xlsm` | **Accept and preserve VBA, never run it**; exported file must carry the correct extension and a report item |
| A2-Q1 decimal | Verify Polars decimal in M0; if immature, store as string with a report warning |
| A2-Q2 `filter` on sheets | v1: output goes to a **new table** (non-destructive). Row hiding waits for `StructureEngine` |
| A2-Q3 extra space | `would_overwrite` error is right for v1 |
| A2-Q4 pipeline deltas on sheets | **One write and one delta per step.** Per-step undo is required by DATA_MODEL section 7; speed is secondary |
| A2-Q5 large `table_to_cells` | v1 cap of **200,000 cells per cell_patch**; larger returns typed `too_large_for_history`. Agents 1, 2 and 3 propose a "write into a new sheet" delta before M2 closes |
| A2-Q6 Jalali library | Own implementation is acceptable if it passes independently sourced fixtures including leap years; any library needs a license check first |

## Conditions

**Agent 1**
- **C1.1** Pure-Python at 100k x 20 is the biggest risk. Measure open time and memory at **E1**, not E9. If it clearly misses the target in TESTING_STRATEGY, stop and bring the Rust-core option to Agent 0 before E3.
- **C1.2** Add to the plan a **snapshot format** (engine-owned, versioned) so a separate process can parse hostile files and hand the result to the API (ADR-011). Needed in Phase 4, designed now.
- **C1.3** Replay determinism: `apply_delta` over a saved workbook must reproduce live state exactly; add as a named test (Agent 3's history rehydration depends on it).
- **C1.4** Revise PLAN.md section 17/19 to mark each CC accepted or changed per the table above, and keep working against `contracts/` v0.2.0.

**Agent 2**
- **C2.1** Sheet-range operations must never silently turn formulas into values; your `range_has_formulas` refusal stands, using the typed `read_range`.
- **C2.2** The M0 Polars-vs-DuckDB spike stays timeboxed to one small PR. Polars-only is the default.
- **C2.3** Write `packages/dataops/docs/PARAMS_SCHEMA.md` (keywords and `x-gridora-*` hints) before M1 so Agent 3 can build the form renderer. Use `extra_targets` for `join`.

**Agent 3**
- **C3.1** Import is **thread-based in v1**; remove the ProcessPool plan from v1 scope and list isolation as a Phase 4 limitation (ADR-011).
- **C3.2** The single-worker, in-memory working copy design is accepted; keep the README limitation (no horizontal scaling) and make the LRU cap and eviction/rehydration tests part of PR 9.
- **C3.3** Move PR 11 (`deploy-stack`) before PR 8, so `docker compose up` is verified early with the stub engine.

## Order of work (all three can start now)

1. Agent 0: contracts v0.2.0 (done in this change).
2. Agent 1: E0 and E1, spike in parallel. Agent 2: M0 and M1. Agent 3: PR 1 to PR 6.
3. First integration check (slice 1: CSV upload to grid) when Agent 1's E1 and Agent 3's PR 5 are both merged.

## Needed from the owner

- A handful of **real Excel-made workbooks** (pivot, chart, VBA, conditional formats, a Persian RTL workbook, a table with structured references). Place them outside the repo or tell Agent 0 if they contain sensitive data; anonymized copies are preferred.
- Later: open exported workbooks in real Excel and report any repair prompt.
- Nothing else blocks the agents.
