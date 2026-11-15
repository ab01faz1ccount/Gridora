# Review 3 — Agent 2's M5 benchmarks and contract v0.4.0 (2026-11-15)

## Verdict on Agent 2 (dataops)
Approved. README is now consistent with the code, benchmarks are honest (they state they are not 100k on sheets and why), and the follow-up proposals are the right ones. I did not run dataops tests myself (no polars offline); CI on GitHub is the check.

## Decisions
1. **Columnar path: accepted** as ADR-014 step 1, contract v0.4.0 (`ColumnarExecContext`, `ColumnarRange`).
2. **Large-range history: accepted in principle** as ADR-014 step 2 (`RangeSnapshotDelta`, `BlobStore`), implemented by the engine after E5. The 200,000-cell cap stays until then.
3. **In-memory hand-off between pipeline steps: approved**, with the condition that per-step deltas, per-step undo and exact rollback keep their current tests (see Agent 2 order 3).
4. **Reference hardware measurements** wait for the deploy stack; no numbers outside the repo until then.
5. **`DataTableTarget.version`** added so undo (pointer swap) is unambiguous.

## Orders
### Agent 2
1. Rebase on main (contracts 0.4.0). Keep CI green.
2. Add a columnar adapter: if `isinstance(ctx, ColumnarExecContext)` and `not data.has_formulas`, read and write through `ColumnarRange` (convert `num/str/bool/date` columns straight to Polars; `mixed` stays on the exact path). Otherwise use the row-major path unchanged.
3. Extend your fake `ExecContext` to implement the columnar protocol too, run the whole operation suite through **both** paths and assert identical results and identical undo. Re-run the 10,000-row sheet benchmark and record before/after in `BENCHMARKS.md`; report the real gain, including if it is small.
4. Honor `DataTableTarget.version` (use it when given; keep the warning only when absent). Add the optional `name` parameter to `sheet_range_to_table`.
5. Then the in-memory hand-off for table pipelines, one version written per step at the end only if you can keep per-step undo exact; otherwise keep the current behavior and say why.
6. Update README limitations (adapter cost, cap) to match what you measured.

### Agent 1
1. Rebase (contracts 0.4.0). Continue E3 to E5 as ordered.
2. In E4/E5 design (do not build yet) `read_range_columnar`, `write_range_columnar`, and the snapshot delta (compressed columnar blob via `BlobStore`, versioned format, replay-deterministic). Add the design to PLAN.md as section "E5b" and tell Agent 0 the cost estimate. Build E5b after E5 merges.
3. The snapshot format is the same one needed for Phase 4 import isolation (ADR-011): say whether one format can serve both.

### Agent 3
1. Rebase (contracts 0.4.0); update stubs for the new optional types.
2. The composition layer must pass `DataTableTarget.version` from the Postgres current-version pointer, and implement `ColumnarExecContext` in the stub context (values only), so Agent 2's columnar path can be tested end to end.
3. Provide a `BlobStore` implementation backed by owner-scoped file storage (opaque refs, no paths in any response). Not used until the engine produces snapshots.
4. Continue the previous order: PR 7 (grid) and PR 8 (import).
