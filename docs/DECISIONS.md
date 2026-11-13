# Gridora — Architecture Decision Records

Format: Context · Decision · Consequences. Status: Proposed → Accepted (after owner review).

## ADR-001 — Modular monolith, no microservices
**Context:** Single internal deployment, small team of agents, need for clean boundaries.
**Decision:** One FastAPI process importing `engine` and `dataops` as Python packages with typed interfaces.
**Consequences:** Simple deployment and debugging. Packages can be split into processes later because they sit behind interfaces. Status: Proposed.

## ADR-002 — Interface-first module boundaries
**Decision:** `WorkbookEngine`, `OperationExecutor`, `TableStore` Protocols in `contracts/`; modules never import each other; `ExecContext` bridges data access.
**Consequences:** Parallel development; stub implementations enable early UI work. Status: Proposed.

## ADR-003 — Spreadsheet engine: own package layer, evaluated formula backend
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

