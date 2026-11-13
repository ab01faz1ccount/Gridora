# packages/dataops — Implementation Plan (Step 0)

Owner: Agent 2 · Branch: `agent2/plan` · Status: **proposal, awaiting Agent 0 review. No implementation code exists.**

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
- **Validation layers:** (a) pydantic schema -> `ValidationError` with JSON-pointer `path` (e.g. `/params/keys/0/column`); (b) `validate_static`; (c) data-dependent checks (column exists, type compatible, target not overwritten) at preview/apply time, returned in `OperationResult.errors` with `status="error"` and **no mutation**. (Reason: the contract's `validate(op)` has no context, see CONTRACT_CHANGE #1.)
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
- Read range -> frame -> `plan()` -> write the result back with `ctx.write_range`, returning the engine's `cell_patch` delta. If the result has **fewer rows** (filter, dedupe) the freed trailing rows inside the original range are written as empty cells in the same call, so the whole effect stays one `cell_patch` and one undo. If the result needs **more** space (e.g. `split_column` adds columns) and the cells to the right are not empty, the op fails with `would_overwrite` before any write; it never shifts or overwrites silently. (Inserting columns is a structure change owned by the engine; see Q3.)
- Ranges containing formulas: ops that move or rewrite cells (sort, dedupe, filter, find_replace, ...) must not silently turn formulas into values. Plan: refuse with `range_has_formulas` unless the params carry `formulas: "convert_to_values"` and the user confirmed. This needs `ExecContext.read_range` to tell me which cells are formulas (see CONTRACT_CHANGE #5).

**C. Operations that create output** (`group_aggregate`, `pivot`, `unpivot`, `join`)
- Source is never touched. Result is stored as a new data table (version 1); `OperationResult.output = DataTableTarget(new_id)`. If the source is a sheet range, the executor first snapshots it into an implicit table via the bridge, then runs the op. Materializing the result into a sheet is a separate step (`table_to_cells` into a new sheet, orchestrated by the API, since creating a sheet is engine territory).
- Delta/undo for "table created": proposed convention `TableVersionDelta(from_version=0, to_version=1)`, meaning "table appeared"; undo hides/removes it (API/Postgres side), redo restores it. Needs Agent 0 confirmation (CONTRACT_CHANGE #3).

**D. Pipelines** (`run_pipeline`)
- Steps run in order, with the frame handed from step to step in memory (no re-reading Parquet). All-or-nothing: temp version files are promoted only if every step succeeds; on failure nothing is committed and the failing step index + errors are returned.
- Table targets: one version per step, so each `OperationResult` carries its own `TableVersionDelta` and ordinary per-step undo works ("Tools produce ordinary history entries", DATA_MODEL section 7).
- Sheet targets: the range is read once and written once; I propose a single combined `cell_patch` delta on the **last** result, earlier results carrying `delta=None` plus `affected`. This deviates from "one delta per result", so it is flagged as Q4 for Agent 0; fallback is a write per step (simpler, slower).
- **Tool bindings:** a step param value of the form `{"$input": "<name>"}` is replaced at run time. Validation (`validate_tool`): every `$input` is declared in `Tool.inputs`; every declared required input is bound; kind compatibility (`column` only where the param schema has `x-gridora-column`; `range` only for range-typed params; `value` must satisfy the param's JSON type); bound columns exist in the target. No expressions or scripting in bindings.

## 5. Polars vs DuckDB split

Principle (ADR-006): **Polars is the default; DuckDB only where SQL over Parquet clearly wins.** Two engines means two sets of null/type/collation semantics, so every use of DuckDB must be justified by a measurement, and results must be forced deterministic (`ORDER BY` / `maintain_order`).

| Work | Engine | Why |
|---|---|---|
| sort, filter, dedupe, fill, find_replace, clean_text, split/merge, change_type, computed_column, convert_calendar | Polars (lazy) | columnar, expression-based, one frame in/out |
| group_aggregate, pivot, unpivot | Polars first | `group_by`, `pivot`, `unpivot` are native; DuckDB only if M0 spike shows a clear win |
| join | DuckDB over Parquet **if** the spike shows a win at 100k x 100k; otherwise Polars `join` | outer joins on large inputs, no need to load both fully |
| table read/write, paging | Polars scan/write_parquet (zstd, ~64k-row groups for page reads) | immutable versions |
| chart aggregation | Polars (shared kernel with `group_aggregate`) | |

**M0 spike (timeboxed to one small PR):** same 100k-row join/group/pivot in both engines, compare wall time, peak memory and null/type/ordering semantics; result goes in `packages/dataops/spikes/` and becomes a DECISIONS.md note. Default if inconclusive: Polars only, DuckDB deferred.

Dependencies to be justified by PR notes to Agent 0 (name, version, license, why, alternatives): `polars`, `duckdb` (only if the spike keeps it), `pytest`, `hypothesis` (dev), `jsonschema` (dev, schema self-check). No `pandas`, no `pyarrow` unless Polars Parquet I/O proves insufficient. Licenses to be verified at PR time, not assumed here.

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

- **Layout:** `TableStore` is constructed by `apps/api` with a path-resolver callback (`path_for(user_id, table_id, version)`), because the API owns the storage layout (ARCHITECTURE section 8); I never invent paths and never return paths.
- **Versions:** immutable Parquet, written via temp + fsync + rename; a content hash and `schema/row_count` are returned in `DataTable` for the API to persist in Postgres (Postgres is the owner of "which version is current"; the store keeps no authoritative pointer).
- **dtype mapping:** contract dtypes -> Polars (`int64`, `float64`, `bool`, `string`, `date`, `datetime`, `decimal`). `decimal` uses a fixed-precision Polars decimal; risk noted in section 10.
- **`read_page(table_id, offset, limit, sort)`:** Parquet scan with slice; sort via the collation key for strings. Needs a `version` argument (CONTRACT_CHANGE #2).
- **`sheet_range_to_table`:** header-row detection heuristic (first row all non-empty, unique strings and later rows contain non-strings or differing types -> header; always overridable via `header_row`); dtype inference over the full column (not a sample) with ordered fallbacks int -> float -> date -> bool -> string; user `dtype_overrides`; mixed-type columns, duplicate/empty headers, formula cells and error cells (`#N/A`, ...) produce warnings; **`preview=True` returns inferred schema + first rows + warnings and stores nothing.** Number cells arrive as floats from the engine; a column becomes `int64` only if every value is integral and within 2^53.
- **`table_to_cells`:** writes header + rows through `ctx.write_range` in chunks (a 100k x 20 table is ~2M cells; one giant `cell_patch` would blow the history budget) — chunking policy and the interaction with the 200 MB history cap to be agreed with Agent 3 (Q5). Refuses to overwrite non-empty cells without confirmation (`would_overwrite`).
- **Refreshable links** re-run the import on demand and never overwrite user edits without confirmation (DATA_MODEL section 4); implemented as a normal bridge call with a diff warning, no background behavior.

## 9. Chart data aggregation

`chart_data(spec: ChartSpec, ctx) -> ChartData` (see CONTRACT_CHANGE #4 for where it lives in the interface).
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

## 12. CONTRACT_CHANGE proposals (for Agent 0; I keep working against the current contracts meanwhile)

1. **`OperationExecutor.validate(op)` has no context**, so column existence and type checks cannot happen there. Proposal: add optional `ctx: ExecContext | None = None` (data-dependent validation when given). Until then: static validation in `validate`, data-dependent errors in `OperationResult.errors`.
2. **`TableStore.read_page` / `restore_version` semantics:** `read_page` has no `version`; after an undo the current version is not the highest one. Proposal: add `version: int | None` to `read_page` (and to `table_to_cells`), with the current-version pointer owned by Postgres/API. Also clarify that `restore_version` is a pointer swap (returns the existing `DataTable` at that version) and does not create a new version.
3. **"Table created" delta:** `TableVersionDelta` has no representation for a newly created table. Proposal: `from_version=0` means "did not exist" (undo = remove from view). Alternatively add an explicit `created: bool`.
4. **No interface for chart data or Tool binding:** `ChartSpec -> ChartData` (`GET /charts/{id}/data`) and `bind/validate Tool` (`POST /tools/{id}/run`, `POST /tools`) have no method in `OperationExecutor`/`TableStore`. Proposal: add `chart_data(spec, ctx) -> ChartData`, `validate_tool(tool, target, ctx) -> list[ValidationError]` and `bind_tool(tool, inputs) -> Pipeline`.
5. **`ExecContext.read_range` returns `list[list[Any]]`:** untyped. I need to know whether cells are contract `CellValue` objects, plain Python values, or serial numbers + number-format hints (dates), and which cells are formulas or errors. Proposal: return `list[list[Cell]]` (or a small typed struct) so formulas, errors and date formats are visible. `ExecContext` also lacks `workspace_id` (needed by `create_from_rows`) and `write_range` has no way to clear trailing cells explicitly (assumed: `None` cell = clear).
6. **`PipelineStep` mismatch:** `docs/DATA_MODEL.md` says `PipelineStep.operation: Omit<Operation,"id"|"target">`, while `models.py` has flat `type/schema_version/params/label`. I work against `models.py`; please confirm it is normative. Also: the `{"$input": name}` binding convention (section 4D) should be documented in the contract.
7. **`Operation.target` is single:** `join` needs a second table. Plan: `params.right_table_id` (+ ownership check by the API against the same `owner_id`). Please confirm, or add `extra_targets`.
8. **i18n catalog ownership:** descriptors carry keys. I ship `src/gridora_dataops/i18n/{fa,en}.json` and a `catalog(locale)` function; Agent 3 would merge it into `apps/web/src/i18n` or serve it with `GET /operations`. Please confirm that this is the intended split (I cannot edit `apps/`).

## 13. Open questions for Agent 0 (non-contract)

- **Q1 Decimal:** is Polars' decimal type acceptable for `decimal`, or should v1 map it to `float64`/`string` with a warning? (Decimal support is less mature; I will verify in M0.)
- **Q2 `filter` on a sheet range:** "show rows matching" in a spreadsheet implies hiding rows (an engine structure change, `SheetStructureDelta`, defined by Agent 1) or rewriting the range with only matching rows (destructive in effect), or writing matches to a new range/table. Proposal for v1: on sheets, `filter` produces an output table (non-destructive, undoable); true row hiding waits for an engine delta type. Please decide.
- **Q3 Inserting columns/rows:** ops that need extra space cannot insert via `ExecContext`. v1 behavior is `would_overwrite` error; OK?
- **Q4 Pipeline deltas on sheets:** single combined delta on the last result vs one write per step (section 4D).
- **Q5 Large `table_to_cells`:** chunking and the history size cap; who enforces it (API) and how the delta is represented.
- **Q6 Jalali library:** own implementation vs library; I will bring fixtures and license facts in a DECISIONS note before choosing.

## 14. Risks

| Risk | Mitigation |
|---|---|
| Sheet ops on formulas silently destroy formulas | refuse by default (`range_has_formulas`), needs typed cells from `ExecContext` (CONTRACT_CHANGE #5) |
| Polars API/semantics shift between versions | pin exact version in lockfile; golden tests on null/ordering semantics |
| Two engines (Polars + DuckDB) disagree on nulls/types/order | Polars default; DuckDB only for measured wins; explicit `ORDER BY`; cross-engine equivalence tests if both are kept |
| Persian collation incorrect for edge cases (hamza, ZWNJ, mixed Latin) | explicit fixture set; documented rules; limitation listed in README rather than claimed |
| Jalali leap-year divergence between arithmetic algorithm and official calendar in far dates | test against independent known dates; document supported year range |
| Large sheet writes (2M cells) exceed history budget | chunking + API-side cap (Q5) |
| Number columns from Excel are floats: integer-looking IDs lose leading zeros or exceed 2^53 | int inference rule (section 8); bridge warns; string override available |
| Preview of sort/dedupe/join needs full-data work | lazy plan + top-k where possible; `total_rows=None` when expensive; measured in benchmarks |
| Time lost on spikes | M0 spike timeboxed to one small PR; default to Polars-only if inconclusive |

## 15. What I will NOT do

Modify `contracts/`, `apps/`, `packages/engine/`, or `docs/`; import `engine`; add free-text scripting or `eval`; apply Persian normalization implicitly; copy external code (any reuse gets a license check and a THIRD_PARTY_NOTICES entry first); claim support without a test.

## 16. Known limitations (current)

Nothing is implemented. Everything in this document is a plan; the module status in `docs/INTEGRATION_PLAN.md` stays **Planned** until M0 lands.
