# Review 5 — status at 2026-11-17 and next orders

Reviewer: Agent 0. Main after PR #47 (engine E6) and PR #46 (dataops columnar).

## Status in one table

| Module | State | Next |
|---|---|---|
| Engine (A1) | E1, E3, E4, E5, E6 merged; formulas (E7) blocked on ADR-003 part 2 | E5b, CC-13, corpus-driven fixes |
| Dataops (A2) | M0 to M5 merged, columnar path merged, **finished and waiting** | Orders below |
| API/Web (A3) | PR 7 grid merged; import UI, edit, operations not built | PR 8, real engine wiring, then UX_SPEC shell |
| Integration | Nothing runs end to end with the real engine | First integrated slice is the priority |

## New document

`docs/UX_SPEC.md` (this PR) is the UX source for Agent 3 and the catalog metadata for Agent 2.

## Orders

### Agent 2 — dataops (you are waiting; here is the next block)

Goal: make the operation catalog *discoverable by non-experts* and ready for the integration, without any contract change.

1. **Task phrases (U1).** For every operation add i18n keys `op.<id>.keywords` (Persian synonyms and task phrases a newcomer would type, e.g. for `remove_duplicates`: تکراری، حذف تکراری، ردیف مشابه، یکتا) and `op.<id>.example` (a tiny before/after example, text or data, for the panel). Serve them through `catalog(locale)`; English falls back per key as today. Add a test that every operation has both keys in `fa`, and that keywords contain no duplicates across unrelated operations without a note.
2. **Effect summary (U2).** Make `preview` and the validation result carry enough numbers for an "effect-stating" Apply button: rows affected/removed/changed, columns added, and a flag when the operation is destructive or irreversible (e.g. `convert_to_values`). Use existing `PreviewResult`/`OperationResult` fields if they exist; if a field is missing, write a `CONTRACT_CHANGE:` note, do not edit `contracts/`.
3. **Suggestions input (U3, small).** Propose, as a design note in `packages/dataops/docs/SUGGESTIONS.md` (no code yet), a read-only `suggest(target, ctx)` that, from a column or range profile (types, null share, duplicates, mixed digit scripts, ي/ك variants, leading/trailing spaces), returns up to 5 ordered operation ids with a Persian reason. Say what it needs from the contract. I will decide before you implement.
4. **Persian copy review.** Re-read all `fa.json` strings as a newcomer would: no jargon, active voice, same terms everywhere. List any term you are unsure about instead of guessing.
5. **Integration readiness.** Write `packages/dataops/INTEGRATION.md`: exactly what `apps/api` must provide (the `ExecContext` methods, `table_store()` binding, `path_for`), the error/envelope mapping, and a ready-to-copy usage snippet. This is for Agent 3; it must match the code at your commit.
6. Update README "does not work" and BENCHMARKS only if something changed. Do not touch the engine or `apps/`.

### Agent 1 — engine
Orders from REVIEW_4 stand (E6 report, E5b-1/E5b-2, CC-13, no E7). Add: run the corpus (`corpus/manifest.json`, including the `private/` files when present) and put the **import time, memory, and report summary per file** in `BENCHMARKS.md`, noting any file the report mis-describes. The `softwiro` workbook (RTL on all 7 sheets, 6,806 formulas, protection) should be checked for: RTL flag exposed per sheet in `SheetMeta`, `sheetProtection` reported, `fullCalcOnLoad` reported.

### Agent 3 — platform
1. Read `docs/UX_SPEC.md` fully before PR 8. Build PR 8 (import UI + compatibility panel) with the shell regions of §3 (top bar, formula bar, side panel host, sheet tabs, status bar) in place, even if empty or disabled with a reason.
2. Wire the real engine (`GRIDORA_ENGINE=real`) and add the e2e test: upload → window → edit → undo. This is the first integrated slice; nothing else outranks it.
3. Implement the F1 messages for `.xls` and encrypted/corrupt files as specified (plain Persian, what and what-to-do).
4. Do not build the task bar or operation panel before PR 11. Do not hard-code the operation list.
5. Record any UX_SPEC item you think is wrong or too costly as a comment in your PR; do not silently diverge.

## Owner actions
- Merge this PR, relay the three blocks above.
- After Agent 3's first integrated slice, run the test protocol in `docs/UX_SPEC.md` §12 and write `docs/reviews/UX_TEST_1.md`.
- Answer the open questions in `UX_SPEC.md` §13 when you can; none blocks Agents 1 and 2.
- Rotate the GitHub App private key if not yet done.
