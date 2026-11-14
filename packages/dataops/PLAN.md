# packages/dataops — Implementation Plan (Step 0)

Owner: Agent 2 · Revision 2 (after `docs/reviews/PHASE2_REVIEW.md`) · Status: **approved with conditions C2.1 to C2.3; M0 in progress.** Working against `contracts/` v0.2.0 (ADR-010).

Revision 2 changes: contract decisions applied (section 12), open questions answered (section 13), pipelines on sheets now write once **per step**, `join` uses `Operation.extra_targets`, the 200,000-cell history cap is adopted, Polars-only is the v1 engine (spike result in `spikes/SPIKE_REPORT.md`), and the `x-gridora-*` vocabulary is documented in `docs/PARAMS_SCHEMA.md` before M1 (C2.3).

Scope reminder: I work only in `packages/dataops/`. I never import `packages/engine` or `apps/*`; sheet data is reached only through `ExecContext`. Anything I need from `contracts/` that is missing or wrong is listed under **CONTRACT_CHANGE** (section 12). Nothing in this plan is claimed as working; every capability becomes "Implemented/Tested" only when a test proves it.

---

## 1. Package layout

```
packages/dataops/
  pyproject.toml                  # package: gridora_dataops (depends on gridora_contracts)
  README.md  PLAN.md  BENCHMARKS.md
  src/gridora_dataops/
    executor.py                   # DataOpsExecutor  (implements OperationExecutor)
    registry.py                   # OperationRegistry, @register decorator
    spec.py                       # OperationSpec base class, ParamsModel base, x-gridora-* schema keywords
    errors.py                     # error codes, ValidationError builders, JSON-pointer helpers
    targets.py                    # target adapters: sheet_range <-> Polars frame, data_table <-> Polars frame
    deltas.py                     # delta construction / inverse helpers
    pipeline.py  tools.py         # pipeline runner, Tool input binding + validation
    expr/                         # GUI expression tree: model, type-check, compile-to-Polars
    ops/                          # one module per operation (sort.py, filter.py, ...)
    tables/                       # ParquetTableStore, parquet_io, bridge (header detect, dtype inference)
    charts.py                     # ChartSpec + source -> ChartData
    persian/                      # normalize.py, digits.py, collation.py, jalali.py
    i18n/                         # fa.json, en.json  (operation labels/descriptions/param titles)
  tests/                          # unit, property, boundary, persian fixtures, fake ExecContext
  benchmarks/                     # seeded 100k-row generator + runner; results go to BENCHMARKS.md
```

Public surface (what `apps/api` imports): `DataOpsExecutor`, `ParquetTableStore`, `catalog(locale)`. Everything else is private.

## 2. Operation list and priority

Names follow `docs/OPERATIONS_CATALOG.md` exactly. "Destructive" flags are copied from the catalog and pinned by a test (a registry-wide test compares the registry against a literal table of the catalog).

| Pri | `type` | Destructive | Notes |
|---|---|---|---|
| P1 | `sort` | no | multi-key, asc/desc, nulls placement, Persian collation (section 6) |
| P1 | `filter` | no | condition tree: text/number/date/empty; see open question Q2 for sheet targets |
| P1 | `remove_duplicates` | **yes** | by chosen columns, keep first/last |
| P2 | `change_type` | **yes** | needed early by the bridge; Persian-digit-aware parsing |
| P2 | `find_replace` | **yes** | whole-cell/partial, case, "ignore variants" (ي/ی, ك/ک) |
| P2 | `fill` | no | down / up / constant |
| P2 | `clean_text` | **yes** | trim, collapse spaces, case, Persian/Arabic letters+digits, tatweel, ZWNJ options |
| P3 | `split_column` | **yes** | delimiter / fixed width |
| P3 | `merge_columns` | no | separator, skip-empty option |
| P3 | `computed_column` | no | expression tree, no scripting (ADR-007) |
| P4 | `group_aggregate` | no | creates output; shares an aggregation kernel with chart data |
| P4 | `pivot` | no | creates output |
| P4 | `join` | no | creates output; inner/left/right/outer |
| P4 | `unpivot` | no | creates output |
| P5 | `convert_calendar` | **yes** | Gregorian <-> Jalali, explicit operation only |

Milestones (each = a small PR with tests, aligned to `docs/INTEGRATION_PLAN.md` slices):

- **M0 Skeleton** — package, registry, executor shell, errors, fake `ExecContext`, descriptor/i18n tests, import-boundary test, Polars-vs-DuckDB micro-spike (section 5).
- **M1 (slice 4)** — `sort`, `filter`, `remove_duplicates` on sheet-range and data-table targets, validate/preview/apply/undo.
- **M2 (slice 5)** — `ParquetTableStore`, sheet<->table bridge, `change_type`, aggregation kernel.
- **M3** — `find_replace`, `fill`, `clean_text`, `split_column`, `merge_columns` (+ Persian modules).
- **M4 (slice 6)** — `computed_column`, `group_aggregate`, `pivot`, `join`, `unpivot`, chart data.
- **M5 (slice 8)** — pipelines, Tool binding/validation, `convert_calendar`, full 100k benchmark pass + `BENCHMARKS.md`.

## 3. Registry and executor design

**One class per operation**, registered with a decorator:

```python
class OperationSpec(Protocol):
    type: str                      # "sort"
    schema_version: int            # current params schema version
    category: str; destructive: bool; supports_preview: bool
    targets: tuple[str, ...]       # ("sheet_range", "data_table")
    Params: type[ParamsModel]      # pydantic model, extra="forbid"
    def validate_static(self, params) -> list[ValidationError]       # cross-field rules, no data needed
    def plan(self, frame: pl.LazyFrame, params, env: PlanEnv) -> OpOutput   # pure: frame in, frame(s) out
    def migrate(self, params, from_version: int) -> dict             # params schema migrations
```

- **Descriptor** is generated, not hand-written: `params_schema = Params.model_json_schema()` plus `x-gridora-*` hints (e.g. `x-gridora-column: true` marks a parameter that holds a column name, so the GUI can render a column picker and Tool bindings can be type-checked). `label` / `description` are i18n keys (`ops.sort.label`, `ops.sort.description`); property titles use `ops.sort.params.<name>`.
- **Purity:** `plan()` is a pure function from a Polars frame + params to a result frame. No globals, no clock, no randomness, no I/O. This gives determinism, cheap preview (lazy plan + `limit`), and one implementation for both target kinds.
- **Executor** owns everything impure. For a request it: (1) resolves the spec (`unknown_operation` if missing), (2) migrates old `schema_version` params, (3) validates, (4) loads the target through a **target adapter**, (5) runs `plan()`, (6) commits through the adapter and builds the delta.
- **Target adapters** (`targets.py`):
  - `data_table` -> `TableStore` read (Parquet scan, lazy). Commit = write new immutable version.
  - `sheet_range` -> `ctx.read_range(range)` -> Polars frame (header handling via a `has_header` param on the op, default from the bridge heuristic). Commit = `ctx.write_range(...)`, which returns the engine-built `Delta`. Dataops never builds `cell_patch` deltas by hand for sheets; the engine computes before/after, so undo is the engine's `apply_delta(inverse=True)`.
- **Validation layers:** (a) pydantic schema -> `ValidationError` with JSON-pointer `path` (e.g. `/params/keys/0/column`); (b) `validate_static`; (c) data-dependent checks (column exists, type compatible, target not overwritten): returned by `validate(op, ctx)` when a context is given (contract v0.2), and always re-checked at preview/apply, where failures come back in `OperationResult.errors` with `status="error"` and **no mutation**. `ValidationError.path` is relative to the Operation root (`/params/column`).
- **Preview:** `preview(op, ctx, limit)` builds the same lazy plan on the **full** data and takes `head(limit)`; it never calls `write_range`, never writes Parquet. `total_rows` is filled when cheap (filter, dedupe, join count), else `None`. A test asserts "no store writes, no `write_range` calls" for every op.
- **Errors:** stable codes in `errors.py` (`unknown_operation`, `invalid_param`, `unknown_column`, `type_mismatch`, `would_overwrite`, `too_many_rows`, ...), all surfaced as contract `ValidationError`. Contract `ERROR_CODES` mapping stays Agent 3's job; I raise typed exceptions with stable `code` strings (architecture section 9).
- **Resource guards:** row/column/expression-node/depth limits and a cell cap per call (configurable), so hostile or accidental huge input fails with a typed error instead of exhausting memory.

## 4. Deltas and undo per operation kind

All operations are undoable. "Destructive" only means explicit user confirmation (API enforces `confirm_destructive`).

**A. In-place on a data table** (`sort`, `filter`, `remove_duplicates`, `find_replace`, `fill`, `clean_text`, `split_column`, `merge_columns`, `change_type`, `computed_column`, `convert_calendar`)
- Apply writes Parquet `v(N+1)` (temp file + fsync + atomic rename; versions are never overwritten) and returns `TableVersionDelta(from_version=N, to_version=N+1)`.
- Undo = `restore_version(table_id, N)` (pointer move; no data recomputation). Redo = restore `N+1`. Because both files exist, "apply inverse delta -> state equals original" is exact by construction and is asserted by content-hash comparison in tests.
- Retention: the API decides when old versions are compacted. If a needed version is gone, `restore_version` raises `version_unavailable` (typed), never silently returns something else.

**B. In-place on a sheet range** (same op list)
- Read range -> frame -> `plan()` -> write the result back with `ctx.write_range`, returning the engine's `cell_patch` delta. If the result has **fewer rows** (filter, dedupe) the freed trailing rows inside the original range are written as empty cells in the same call, so the whole effect stays one `cell_patch` and one undo. If the result needs **more** space (e.g. `split_column` adds columns) and the cells to the right are not empty, the op fails with `would_overwrite` before any write; it never shifts or overwrites silently. (Inserting columns is a structure change owned by the engine's optional `StructureEngine`; v1 decision: `would_overwrite` is correct.)
- Ranges containing formulas: ops that move or rewrite cells (sort, dedupe, filter, find_replace, ...) must not silently turn formulas into values. Plan: refuse with `range_has_formulas` unless the params carry `formulas: "convert_to_values"` and the user confirmed. The typed `read_range` (contract v0.2: `Cell | None`, formulas visible in `Cell.f`) provides this. Condition C2.1 of the Phase 2 review confirms the refusal stands. `write_range` writes values only and clears uncovered cells of the range, so shrinking results are one call and one delta.

**C. Operations that create output** (`group_aggregate`, `pivot`, `unpivot`, `join`)
- Source is never touched. Result is stored as a new data table (version 1); `OperationResult.output = DataTableTarget(new_id)`. If the source is a sheet range, the executor first snapshots it into an implicit table via the bridge, then runs the op. Materializing the result into a sheet is a separate step (`table_to_cells` into a new sheet, orchestrated by the API, since creating a sheet is engine territory).
- Delta/undo for "table created": proposed convention `TableVersionDelta(from_version=0, to_version=1)`, meaning "table appeared"; undo hides/removes it (API/Postgres side), redo restores it. Confirmed by Agent 0 and documented in contract v0.2 (`from_version == 0` means the table did not exist).

**D. Pipelines** (`run_pipeline`)
- Steps run in order, with the frame handed from step to step in memory (no re-reading Parquet). All-or-nothing: temp version files are promoted only if every step succeeds; on failure nothing is committed and the failing step index + errors are returned.
- Table targets: one version per step, so each `OperationResult` carries its own `TableVersionDelta` and ordinary per-step undo works ("Tools produce ordinary history entries", DATA_MODEL section 7).
- Sheet targets: **one read-modify-write and one `cell_patch` delta per step** (Phase 2 decision A2-Q4). Per-step undo is required by DATA_MODEL section 7; speed is secondary. All-or-nothing is kept by checking every step in memory first and only then writing; if a later write fails, the already-written steps are reverted by applying their inverse deltas through the context.
- **Tool bindings:** a step param value of the form `{"$input": "<name>"}` is replaced at run time (`bind_tool`, documented in the contract). Validation (`validate_tool(tool, target, ctx?)`): every `$input` is declared in `Tool.inputs`; every declared required input is bound; kind compatibility (`column` only where the param schema has `x-gridora-column`; `range` only for range-typed params; `value` must satisfy the param's JSON type); bound columns exist in the target. No expressions or scripting in bindings.

## 5. Polars vs DuckDB split

Principle (ADR-006): **Polars is the default; DuckDB only where SQL over Parquet clearly wins.** Two engines means two sets of null/type/collation semantics, so every use of DuckDB must be justified by a measurement, and results must be forced deterministic (`ORDER BY` / `maintain_order`).

| Work | Engine | Why |
|---|---|---|
| sort, filter, dedupe, fill, find_replace, clean_text, split/merge, change_type, computed_column, convert_calendar | Polars (lazy) | columnar, expression-based, one frame in/out |
| group_aggregate, pivot, unpivot | Polars first | `group_by`, `pivot`, `unpivot` are native; DuckDB only if M0 spike shows a clear win |
| join | Polars `join` (spike result) | revisit DuckDB only if a measured case exceeds memory |
| table read/write, paging | Polars scan/write_parquet (zstd, ~64k-row groups for page reads) | immutable versions |
| chart aggregation | Polars (shared kernel with `group_aggregate`) | |

**M0 spike (done, `spikes/SPIKE_REPORT.md`):** at 100k rows Polars was faster than DuckDB on every join/group/pivot workload (e.g. inner join 0.012 s vs 0.068 s), memory was equal or lower, results were identical, and Polars' decimal type round-tripped through Parquet. The spike did not cover larger-than-memory data or multi-core machines. **Decision proposed for DECISIONS.md: Polars-only in v1; `duckdb` is not added as a dependency** (and DuckDB's Arrow hand-off would also need `pyarrow`). The table above is amended accordingly: `join`, `group_aggregate`, `pivot` and `unpivot` run in Polars.

Dependencies to be justified by PR notes to Agent 0 (name, version, license, why, alternatives): `polars`, `pytest`, `hypothesis` (dev), `jsonschema` (dev, schema self-check). No `pandas`, no `pyarrow` unless Polars Parquet I/O proves insufficient. Licenses to be verified at PR time, not assumed here.

## 6. Persian-specific operations

All Persian handling is explicit, user-chosen and previewable; nothing is applied silently (I18N_SPEC).

- **`clean_text` options** (each a checkbox in the schema): `trim`, `collapse_spaces`, `nbsp_to_space`, `case` (upper/lower/title, Latin only), `arabic_letters_to_persian` (`ي ى`->`ی`, `ك`->`ک`), `digits` (`none | to_latin | to_persian | to_arabic_indic`), `remove_tatweel` (`ـ`), `zwnj` (`keep | remove | to_space`), `remove_diacritics`. Implemented with vectorized Polars `str.replace_many` / translation tables, not Python loops.
- **Digits:** one canonical module (`persian/digits.py`) covers Persian `۰-۹`, Arabic-Indic `٠-٩`, and numeric punctuation (`٬` thousands, `٫` decimal, `،` as separator where numeric parsing allows). Storage stays canonical Latin; used by `change_type`, the bridge inference (on request), and `clean_text`.
- **Persian-aware sort:** Polars sorts by code point, which is wrong for Persian (پ چ ژ گ sit outside the alphabetical code-point order). Plan: build a **collation key** column by vectorized mapping of each character to an order-preserving code (Persian alphabetical order; ي/ك folded into ی/ک; digits normalized; Latin case-folded; punctuation first), then sort on the key and drop it. No ICU/PyICU (native system dependency, awkward for offline builds). Stable sort; tie order = original row order. Verified by hand-written ordered fixtures.
- **Search ignoring variants:** `find_replace` and `filter` text conditions accept `ignore_variants: true`, comparing on the normalized form (ي/ی, ك/ک, optionally digits) while replacing in the original text.
- **`convert_calendar`:** Gregorian date column <-> Jalali. Jalali is represented as text `YYYY/MM/DD` (digits per user option) or three integer columns; Gregorian stays the stored date type (storage is Gregorian/Excel serial per I18N_SPEC). Parsing accepts Persian/Arabic digits and `/`, `-`, `.` separators. **Library choice goes through DECISIONS.md:** candidates are an own vectorized implementation of the arithmetic (33-year-cycle) algorithm vs an existing Jalali library; decision criteria are license, offline/pinned install, vectorization (100k rows), and agreement with a fixture set of known conversions including leap years. I will not pick before checking licenses and the fixture results.
- **Sheet/table names, headers:** duplicate/empty header names get deterministic fallbacks (`ستون ۱`-style key `columns.unnamed` with index), reported as warnings.

## 7. Expression builder (`computed_column`)

A structured JSON tree, never a string to `eval`:

```
Expr = {lit: value} | {col: name} | {op: "add|sub|mul|div|mod|pow|concat|eq|ne|lt|le|gt|ge|and|or|not", args: [Expr]}
     | {fn: "<allowlisted function>", args: [Expr]}
     | {if: Expr, then: Expr, else: Expr}
```
Allowlist (v1): math (`round, abs, floor, ceil, min2, max2`), text (`upper, lower, trim, len, left, right, substring, replace, concat`), logic (`if, is_null, coalesce`), date parts (`year, month, day`, Gregorian). Steps: schema validation -> type inference/type-check (errors point at the node via JSON pointer, e.g. `/params/expr/args/1`) -> compile to a Polars expression. Caps on depth and node count. Division by zero yields null plus a warning, not an exception. No user-defined functions, no I/O, no recursion.

## 8. Data Table store and bridge

- **Layout:** `create_table_store(path_for: PathResolver)` receives `PathResolver(owner_id, table_id, version)` from `apps/api`, because the API owns the storage layout (ARCHITECTURE section 8); I never invent paths and never return paths.
- **Versions:** immutable Parquet, written via temp + fsync + rename; a content hash and `schema/row_count` are returned in `DataTable` for the API to persist in Postgres (Postgres is the owner of "which version is current"; the store keeps no authoritative pointer).
- **dtype mapping:** contract dtypes -> Polars (`int64`, `float64`, `bool`, `string`, `date`, `datetime`, `decimal`). `decimal` uses a fixed-precision Polars decimal (verified for the pinned version in the spike); decision A2-Q1: if it proves immature in M2 tests, store as `string` with a report warning.
- **`read_page(table_id, offset, limit, sort)`:** Parquet scan with slice; sort via the collation key for strings. Takes the contract's optional `version` argument; the current-version pointer is owned by Postgres/API. `restore_version` is a pointer swap and raises `version_unavailable` if compacted.
- **`sheet_range_to_table`:** header-row detection heuristic (first row all non-empty, unique strings and later rows contain non-strings or differing types -> header; always overridable via `header_row`); dtype inference over the full column (not a sample) with ordered fallbacks int -> float -> date -> bool -> string; user `dtype_overrides`; mixed-type columns, duplicate/empty headers, formula cells and error cells (`#N/A`, ...) produce warnings; **`preview=True` returns inferred schema + first rows + warnings and stores nothing.** Number cells arrive as floats from the engine; a column becomes `int64` only if every value is integral and within 2^53.
- **`table_to_cells`:** v1 cap of **200,000 cells per `cell_patch`** (Phase 2 decision A2-Q5): a larger write returns the typed error `too_large_for_history` (a 100k x 20 table is ~2M cells). Before M2 closes, Agents 1, 2 and 3 propose a "write into a new sheet" delta; I will contribute the dataops side of that proposal. Refuses to overwrite non-empty cells (`would_overwrite`).
- **Refreshable links** re-run the import on demand and never overwrite user edits without confirmation (DATA_MODEL section 4); implemented as a normal bridge call with a diff warning, no background behavior.

## 9. Chart data aggregation

`chart_data(spec: ChartSpec, ctx) -> ChartData` (contract v0.2: `OperationExecutor.chart_data`).
- Source table/range -> Polars frame; each series: group by `category_col` (if any) with `aggregate` (`sum|avg|count|min|max`; default no aggregation = plain values), via the same kernel as `group_aggregate`.
- Deterministic category order: first appearance in the source (user controls order by sorting the source). Nulls stay `None` in series values; null categories get a stable placeholder key. `scatter` returns x values as `categories` and y as the series. `pie` is a single series.
- Guards: too many distinct categories -> typed error `chart_too_many_categories` (default cap configurable), since `ChartData` has no warnings field.
- Output only contains plain values (`ChartData`), nothing ECharts-specific.

## 10. Test plan

Tooling: pytest, hypothesis, ruff, mypy (strict on `src/`), a jsonschema self-check. CI-friendly: all unit tests run on tiny frames; performance tests are separate.

**Per-operation matrix (every op, every applicable target kind)** — a parametrized test module enforces that no registered op is missing any of these:
1. *validate:* schema errors give correct JSON-pointer `path` and code; unknown column / bad type caught at preview/apply with no mutation.
2. *preview:* correct sample, correct `total_rows` when provided, **zero side effects** (fake store records writes; fake `ExecContext` records `write_range` calls).
3. *apply:* expected result on hand-built fixtures, including nulls, empty frames, single row, Unicode/Persian text, duplicate headers.
4. *undo/redo:* apply -> apply inverse delta -> state equals original (table: content hash of the version; sheet: fake grid `apply_delta(inverse)` equals original grid) -> redo equals applied state.
5. *determinism:* same input twice -> identical output (including order); no dependence on locale/time.
6. *destructive flag* equals the catalog table; `supports_preview` equals the catalog.

**Registry/descriptor tests:** every descriptor's `params_schema` is valid JSON Schema; every label/description/param-title key exists in both `fa.json` and `en.json` (Persian text present and non-empty); registry keys are unique; `isinstance(executor, OperationExecutor)` passes (runtime-checkable Protocol from `contracts/`).

**Boundary test:** AST scan asserting no import of `gridora_engine`, `apps`, or anything outside `gridora_contracts` + allowed third-party packages; also asserts no file/network access outside the store's resolver.

**Property tests (hypothesis):** sort is stable and idempotent; dedupe is idempotent and keeps first/last as specified; `clean_text` is idempotent; fill never changes non-empty cells; `change_type` round-trips numeric text with Persian digits; Jalali<->Gregorian round trip over a wide date range; bridge `sheet -> table -> sheet` preserves values for typed columns.

**Persian fixtures:** Persian column names, mixed ي/ی and ك/ک, Persian/Arabic digits, ZWNJ, tatweel, ordered-collation fixtures, Jalali leap-year boundary dates (expected values written by hand from an independent source and recorded in the test file with their provenance).

**Store tests:** version immutability (attempt to overwrite -> error), atomic write (simulated crash leaves no partial version), `restore_version`, paging and sort, dtype round trips for all contract dtypes.

**Pipeline/Tool tests:** step failure -> nothing committed; per-step deltas on tables; binding validation (undeclared input, wrong kind, missing required, non-existent column); a Tool applied twice with different bindings.

**Chart tests:** each chart type, each aggregate, nulls, empty source, category cap.

## 11. Measuring 100k-row performance

- `benchmarks/generate.py`: seeded, deterministic 100,000 rows x 20 columns (ints, floats, bool, dates, Persian and Latin strings including Persian digits, ~10% nulls, ~10% duplicate rows, a low-cardinality key column for group/pivot/join, a second 100k-row table for joins).
- `benchmarks/run.py`: for every op, **through the public executor** (not internal functions), on both a data-table target and a sheet-range target backed by the in-memory fake `ExecContext` (note: engine cost is excluded from the sheet numbers and is stated as such). Metrics: preview time at limit 100, apply time, Parquet write/read time, peak RSS. Method: one warm-up, then 5 runs, report median and worst; each op in a fresh subprocess so `ru_maxrss` is meaningful (Rust allocations are invisible to `tracemalloc`).
- Output: `BENCHMARKS.md` with the exact command, date, commit hash, library versions and hardware description (CPU model, cores, RAM, disk type). Numbers are reported as measured; budgets (TESTING_STRATEGY: "seconds, with progress for slower ops") are stated as targets, never as claims. Any op that misses a budget is listed under known limitations.
- CI runs only a 10k-row smoke benchmark with generous thresholds to catch accidental quadratic behavior; the full 100k run is a documented manual/nightly command.

## 12. Contract decisions (from `docs/reviews/PHASE2_REVIEW.md`, contracts v0.2.0)

| # | My request | Decision | How the plan applies it |
|---|---|---|---|
| 1 | `validate(op, ctx?)` | Accepted | section 3 |
| 2 | `version` on `read_page`/`table_to_cells`; `restore_version` = pointer swap | Accepted | section 8 |
| 3 | "table created" delta | Accepted: `from_version=0` | section 4C |
| 4 | `chart_data`, `validate_tool`, `bind_tool` | Accepted on `OperationExecutor` | sections 4D, 9 |
| 5 | typed `read_range`, `workspace_id`, clearing cells | Accepted: `Cell \| None`; `write_range` writes values, uncovered cells cleared | sections 4B, 8 |
| 6 | `PipelineStep` shape | Flat `models.py` is normative; `$input` documented | section 4D |
| 7 | second table for `join` | **Changed:** `Operation.extra_targets`, not `params` | `join` reads `op.extra_targets[0]`; ownership is verified by the API |
| 8 | i18n catalog split | Accepted: `fa.json`/`en.json` + `catalog(locale)`; API serves `GET /operations/i18n` | section 1 |

Module entry points fixed by the contract (nothing else is imported by `apps/api`): `gridora_dataops.create_executor(config)`, `create_table_store(path_for)`, `catalog(locale)`.

## 13. Decisions on my open questions

| Q | Decision | Consequence for the plan |
|---|---|---|
| Q1 Decimal | Verify in M0; if immature, store as string with a warning | Verified for polars 2.1.0 in the spike; re-checked in M2 |
| Q2 `filter` on sheets | v1: output goes to a **new table** (non-destructive); row hiding waits for `StructureEngine` | `filter` on a sheet range returns `output=DataTableTarget` with a `TableVersionDelta(from_version=0, ...)`; on a data table it stays in place |
| Q3 extra space | `would_overwrite` is right for v1 | section 4B |
| Q4 pipeline deltas on sheets | One write and one delta per step | section 4D |
| Q5 large `table_to_cells` | 200,000 cells per patch; `too_large_for_history` above | section 8 |
| Q6 Jalali | Own implementation acceptable if it passes independently sourced fixtures incl. leap years; any library needs a license check first | section 6; fixtures sourced independently before M5 |

Conditions: **C2.1** formula refusal stands (section 4B); **C2.2** spike timeboxed, Polars-only default (done, section 5); **C2.3** `docs/PARAMS_SCHEMA.md` written before M1 (this revision), `extra_targets` for join.

## 14. Risks

| Risk | Mitigation |
|---|---|
| Sheet ops on formulas silently destroy formulas | refuse by default (`range_has_formulas`) using the typed `read_range` |
| Polars API/semantics differences at the pinned version | single engine (spike result); exact pin; golden tests on null/ordering semantics |
| Persian collation incorrect for edge cases (hamza, ZWNJ, mixed Latin) | explicit fixture set; documented rules; limitation listed in README rather than claimed |
| Jalali leap-year divergence between arithmetic algorithm and official calendar in far dates | test against independent known dates; document supported year range |
| Large sheet writes (2M cells) exceed history budget | 200,000-cell cap with `too_large_for_history`; new-sheet delta proposal before M2 closes |
| Number columns from Excel are floats: integer-looking IDs lose leading zeros or exceed 2^53 | int inference rule (section 8); bridge warns; string override available |
| Preview of sort/dedupe/join needs full-data work | lazy plan + top-k where possible; `total_rows=None` when expensive; measured in benchmarks |
| Time lost on spikes | M0 spike timeboxed to one small PR; default to Polars-only if inconclusive |

## 15. What I will NOT do

Modify `contracts/`, `apps/`, `packages/engine/`, or `docs/`; import `engine`; add free-text scripting or `eval`; apply Persian normalization implicitly; copy external code (any reuse gets a license check and a THIRD_PARTY_NOTICES entry first); claim support without a test.

## 16. Known limitations (current)

Nothing beyond M0 is implemented. Everything in this document is a plan unless a test proves otherwise; the module status in `docs/INTEGRATION_PLAN.md` stays **Planned** until M0 is merged.
