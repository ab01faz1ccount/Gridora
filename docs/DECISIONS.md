# Gridora — Architecture Decision Records

Format: Context · Decision · Consequences. Status: Proposed → Accepted (after owner review).

## ADR-001 — Modular monolith, no microservices
**Context:** Single internal deployment, small team of agents, need for clean boundaries.
**Decision:** One FastAPI process importing `engine` and `dataops` as Python packages with typed interfaces.
**Consequences:** Simple deployment and debugging. Packages can be split into processes later because they sit behind interfaces. Status: Proposed.

## ADR-002 — Interface-first module boundaries
**Decision:** `WorkbookEngine`, `OperationExecutor`, `TableStore` Protocols in `contracts/`; modules never import each other; `ExecContext` bridges data access.
**Consequences:** Parallel development; stub implementations enable early UI work. Status: Proposed.

## ADR-003 — Spreadsheet engine: own package layer, evaluated formula backend (part 1 Accepted; part 2 Pending)
**Context:** Need OOXML fidelity and formula evaluation. Candidates are young projects; README claims are unverified.
**Decision (provisional):** Build the OOXML package/preservation layer ourselves behind `WorkbookEngine`. Run a time-boxed Phase 2 spike on IronCalc (and GridCraft/Gridline for ideas) to decide whether to bind a Rust formula/XLSX core via PyO3/maturin or a JSON-RPC subprocess. No Rust until the spike shows a measurable benefit.
**Consequences:** No dependency on a single external project. Decision is revisited with data. Status: Proposed, pending spike.

## ADR-004 — Server-authoritative workbook, windowed transport
**Decision:** Workbook lives in the backend; the browser fetches viewport windows and sends edits as operations.
**Consequences:** Handles ~100k rows without shipping whole sheets; requires session-cached working copies. Status: Proposed.

## ADR-005 — History via operations with inverse deltas
**Decision:** All edits are Operations; each yields a Delta enabling undo/redo. Table edits create immutable versions (undo = pointer swap).
**Consequences:** Same mechanism powers history and reusable workflows. Status: Proposed.

## ADR-006 — Data Tables stored as versioned Parquet, queried with Polars/DuckDB
**Decision:** Parquet files per version, metadata in Postgres. Polars for transformations; DuckDB only for SQL-shaped work (joins, aggregates over Parquet).
**Consequences:** Fast, simple, no data in Postgres rows for large tables. Status: Proposed.

## ADR-007 — Reusable workflows are saved parameterized pipelines (no scripting in v1)
**Decision:** A Tool is a Pipeline plus named inputs. No user scripting or expression language beyond a GUI expression builder.
**Consequences:** Safe by construction; scripting can be added later behind the same interface. Status: Proposed.

## ADR-008 — Local accounts first
**Decision:** argon2id local accounts and server-side sessions; LDAP/OIDC later.
**Consequences:** Works offline in any network. Status: Accepted — owner confirmed local accounts are enough for v1.

## ADR-009 — Persian-first UI with RTL
**Decision:** All UI strings go through i18n from day one; layout is RTL-aware (logical CSS properties); the grid supports RTL sheets. Locale handling for Jalali dates and Persian digits is scoped in Phase 2.
**Consequences:** Affects grid component design early, which is cheaper than retrofitting. Status: Accepted.

## ADR-010 — Contract v0.2 (Phase 2 review outcome)
**Decision:** Accept the agents' CONTRACT_CHANGE proposals as recorded in `docs/reviews/PHASE2_REVIEW.md`: typed `read_range`/value-only `write_range`, `extra_targets` on Operation, `validate(op, ctx?)`, `chart_data`/`validate_tool`/`bind_tool`, versioned `read_page`, `close`, `file_id`, optional `FormattingEngine` and `StructureEngine`, request/response models with `base_seq`, window cap 1000x100, three more error values. Real modules export fixed factory functions.
**Consequences:** Python and TypeScript contracts bumped to 0.2.0. Agents rebase before coding. Status: Accepted.

## ADR-011 — Import isolation deferred to Phase 4
**Context:** Agent 3 planned imports in a ProcessPool with resource limits, but an in-memory `WorkbookHandle` cannot be returned from another process.
**Decision:** v1 imports in a worker thread under the engine's own budgeted limits plus a timeout. Phase 4 adds process isolation using an engine-defined snapshot format (Agent 1 proposes it in the engine plan revision).
**Consequences:** Hostile-file safety in v1 relies on the engine's limits; this is stated in the README and SECURITY_MODEL. Status: Accepted.

## ADR-003 update (after the engine spike, Agent 1 report E2)
**Part 1 — Accepted:** Gridora owns the OOXML package layer (unknown parts preserved byte-for-byte). Neither IronCalc nor openpyxl preserves unknown parts, so option D (wrap one library) is rejected.
**Part 2 — Pending:** formula core (A: bind IronCalc, B: subprocess, C: own pure-Python). Not decided because the evidence is incomplete: no source build of IronCalc, no change-diff test for dependents, spill untested, no real Excel files. The decision is needed at E7; nothing in E3–E6 depends on it. Gate: Agent 1 completes the four open items in SPIKE_REPORT section 1.4 and the owner supplies real Excel files.

## ADR-012 — Polars only for v1; DuckDB not adopted
**Context:** Agent 2's M0 spike measured 100k-row join/group/pivot/decimal in both engines (1-core sandbox, small scale).
**Decision:** Polars only. No `duckdb` dependency. Revisit only if a measured case (for example a join larger than memory) fails with Polars.
**Consequences:** One set of null/type/order semantics. The spike did not test out-of-core data or multi-core machines. Status: Accepted.

## ADR-013 — Contract v0.3.0
**Decision:** `export_csv` returns a `CompatibilityReport` (CC-9) so neutralized or unencodable cells are never silent. Snapshot protocol (CC-10) deferred to Phase 4. The 200,000-cell per-patch cap (CC-11) is enforced by both the engine when building deltas and `apps/api`.
**Consequences:** Agent 1 and Agent 3 update implementations and stubs. Status: Accepted.

## ADR-014 — Columnar sheet access and large-range history (contract v0.4.0)
**Context:** Agent 2's benchmarks (`packages/dataops/BENCHMARKS.md`) show the cell-by-cell adapter costs about 7 microseconds per cell, and CC-11 caps a `cell_patch` at 200,000 cells. A 100k x 20 sheet is 2,000,000 cells, so no in-place operation (sort, dedupe) could run on a sheet at the product's own size target. Data Tables are not affected (0.04 to 1.0 s at 100k rows).
**Decision (two steps, both additive and optional):**
1. **Columnar path (now).** Optional `ColumnarExecContext`: `read_range_columnar` / `write_range_columnar` exchange `ColumnarRange` (plain Python column lists, typed fast paths, exact `mixed` fallback; `has_formulas` forces the row-major path). dataops feature-detects it and keeps the row-major path as fallback. Removes the pydantic-per-cell cost.
2. **Range snapshot delta (after engine E5).** Reserved `RangeSnapshotDelta` plus `BlobStore`: before/after contents of a large range are stored as compressed, engine-versioned blobs; undo restores the blob. The 200,000-cell cap stays until an engine produces this delta; then it is lifted (new decision).
Also: `DataTableTarget.version` (apps/api passes the current pointer, fixing the "highest version" ambiguity after undo) and `sheet_range_to_table(name=...)`.
**Consequences:** Nothing existing changes. A fake context in dataops can implement the columnar protocol immediately. The real engine implements both after E5 (value edits and deltas) and E4 (reading). Status: Accepted. Not measured on the real engine yet; the gain is expected, not demonstrated.

## ADR-015 — ColumnarEngine accepted; long whole-sheet work; import isolation stays Phase 4 (contract v0.4.1)
**Context:** Agent 1 finished E5 and measured: lazy XLSX open 0.85 s at 100k x 20, but a full parse of every row costs 11 to 13 s (about 27 s counting contract `Cell` objects). Any whole-sheet operation (recalculation, convert to table, in-place sort) pays this.
**Decisions:**
1. CC-12 **accepted** as the optional `ColumnarEngine` protocol (contract 0.4.1). Build order: E6 (export), then E5b-1 (columnar), then E5b-2 (snapshot deltas, codec profile R only).
2. **Codec profile W (whole-workbook snapshot for import isolation) is not built before Phase 4.** One codec and container, two profiles, as Agent 1 proposed; only profile R is in scope now. The tension Agent 1 found (isolation means parsing in a worker, and a 100k x 20 parse takes 11 to 13 s) is real; the thread-based import of ADR-011 stands for v1 and the numbers go into the Phase 4 decision.
3. **Whole-sheet work runs as a job with progress**, never inside a request. Agent 1 proposes how long engine calls report progress and can be cancelled (CC-13); Agent 3's job runner consumes it.
4. **History limit error:** top-level `operation_conflict` plus detail code `too_large_for_history` (what apps/api already does). The engine's `validation_failed` with a reason is aligned to this.
5. **ADR-003 part 2 (formula core) is still pending** and E7 stays blocked. Gate: E6 merged, owner-supplied real Excel files measured, and the full-parse time of those files known. If a real 100k x 20 file needs more than 30 s to parse in pure Python, the Rust-core option is brought back for a decision before any formula work.
**Consequences:** A dataops run on large sheets still waits for E5b; until then large sheet operations return `too_large_for_history`. Status: Accepted.

