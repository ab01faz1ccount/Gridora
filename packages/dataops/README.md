# packages/dataops — Data Operations & Analytics

Owner: Agent 2. Brief: [agents/AGENT_2_DATAOPS.md](../../agents/AGENT_2_DATAOPS.md). Plan: [PLAN.md](PLAN.md). Operation list: [docs/OPERATIONS_CATALOG.md](../../docs/OPERATIONS_CATALOG.md). Form vocabulary: [docs/PARAMS_SCHEMA.md](docs/PARAMS_SCHEMA.md).

**Status: M0 to M5 implemented and merged (15 operations, Data Tables, pipelines, Tools, chart data); 345 tests (the whole suite also runs through the columnar double); benchmarks in `BENCHMARKS.md`. Contract version: 0.4.0.** Phase 2 review orders applied (README corrected, CI sequence run locally, conformance test added).

## What works (each item is covered by a test in `tests/`)
- `create_executor(config)` returns a `DataOpsExecutor` that satisfies the contract's `OperationExecutor` protocol (`isinstance` check).
- Executor on **sheet ranges and data tables** for all 15 operations: schema validation with JSON-pointer paths relative to the Operation root, data-dependent column checks (`validate(op, ctx)`, including `extra_targets` columns), preview with zero side effects, apply with ONE `write_range` call (sheets, one engine delta) or ONE new immutable version (tables, `TableVersionDelta`), exact undo via the delta, refusal to turn formulas into values, `would_overwrite` instead of silent overwrite, configurable per-patch cell cap (`max_patch_cells`, default 200,000, error `too_large_for_history`).
- Registry + descriptor generation: JSON Schema from pydantic params, i18n keys for titles/descriptions/enum labels, `x-gridora-*` hints.
- `catalog(locale)`: Persian text for categories and every error code; English falls back to Persian per key.
- Boundary test: no import of `gridora_engine`/`apps`, no network/process modules, no unreviewed third-party packages.
- Polars-vs-DuckDB spike with measured numbers: `spikes/SPIKE_REPORT.md`.
- **`sort`**: multi-key, stable (ties keep original order), nulls first/last, Persian alphabetical collation (`persian/chars.py`: آ ا ب پ ... ی; ي/ك folded; digits of all scripts equal; Latin before Persian) or binary; undo via the engine delta.
- **`remove_duplicates`**: chosen columns or all, keep first/last, case-insensitive by default, optional Persian/Arabic variant folding; idempotent (property-tested).
- **`filter`**: condition tree (and/or groups, nested), text/number/date/bool/empty tests, `between`, variant-insensitive matching; type errors point at the exact node (`/params/where/items/1/value`). Preview works on sheets; **applying a filter on a sheet range is not implemented yet** (it creates a new table, needs the TableStore, M2).
- **`find_replace`** (literal, never a user regex; partial/whole cell; case option; `ignore_variants` matches ي/ی, ك/ک, digits of all scripts and tolerates tatweel/ZWNJ/diacritics *without* touching the rest of the cell), **`fill`** (down/up/constant; blank text counts as empty; never changes a non-empty cell), **`clean_text`** (whitespace, case, Persian/Arabic letters, digit scripts, tatweel, ZWNJ, diacritics; every Persian option off by default; idempotent), **`split_column`** (delimiter or fixed width, `max_parts`, merge repeated delimiters, unique names), **`merge_columns`** (skips empties, formats numbers/dates as text, unique output name).
- **`group_aggregate`** (sum/avg/count/count_distinct/min/max, groups in first-appearance order or Persian-sorted, grand total with no `by`), **`pivot`** (max 200 new columns), **`unpivot`** (mixed types become text with a warning), **`join`** (inner/left/right/full on one or more keys, second table from `Operation.extra_targets[0]` — a data table or a sheet range, optional variant-insensitive keys, deterministic order, guard at 5,000,000 matching rows). All four **always create a new table** and never touch the source (`TableVersionDelta(from_version=0, to_version=1)`).
- **`computed_column`**: structured expression tree (literal / column / call of ~35 allow-listed functions), type-checked before running, errors point at the node (`/params/expr/args/1`), division by zero gives empty cells + a warning, limits of depth 20 and 200 nodes, no scripting.
- **`chart_data(spec, ctx)`**: bar/line/pie/scatter/area -> plain categories and series (aggregate sum/avg/count/min/max per category in first-appearance order, nulls kept, `(خالی)` for empty categories, caps at 5,000 categories).
- **`convert_calendar`** (Gregorian ⇄ Jalali, explicit only): date -> text `YYYY/MM/DD` with Persian or Latin digits, or three integer columns; Jalali text (any digit script, `/ - .` separators) -> date; replaces the column or writes a new one; unconvertible values fail with a count and examples, or become empty with a warning. Own implementation of the 33-year arithmetic cycle, **supported Jalali years 1300-1500**, checked against jdatetime and persiantools on every one of the 73,413 days of that range (all three libraries incl. convertdate agree on year starts from 1277); outside the range values are reported, never guessed.
- **Pipelines** (`run_pipeline`): all-or-nothing, one result with its own delta per step. A dry run first plans every step on in-memory frames, chained exactly as they will run (including the growing/shrinking sheet range and steps that create a new table); only if everything passes are the steps applied one by one. A failure while applying rolls back earlier steps (table versions/tables created by the run are discarded, sheet cells are restored value by value) and says so if the rollback itself was incomplete (`rollback_incomplete`).
- **Tools**: `bind_tool` replaces `{"$input": name}` placeholders (an unbound *optional* input drops the parameter so the default applies; wrong kinds, unknown/missing inputs and undeclared placeholders are reported with paths); `validate_tool` checks, without running anything, that column inputs sit at column parameters, value inputs at plain-value parameters, every input is used, operations exist and the static parameters are valid; with a context it also checks the first step's literal columns.
- **`change_type`**: text/number/bool/date/datetime conversions; Persian/Arabic-Indic digits, `٬ ، ,` thousands separators and `٫` decimal separator understood; comma is only a decimal separator when asked (`decimal_separator=comma`); failures stop the operation with a count and examples (or become empty with `on_error=null` and a warning).
- **`ParquetTableStore`** (`create_table_store(path_for)`): immutable zstd Parquet versions written atomically (temp + fsync + hard link, never overwrites), `read_page` with Persian-aware stable sort, `restore_version` as a pointer swap (`version_unavailable` if compacted), per-owner isolation, all contract dtypes round-trip (decimal stored as Decimal(38,10)).
- **Bridge**: `sheet_range_to_table` (explicit `header_row`, whole-number floats become int64, mixed columns become text and error cells empty *with warnings*, dtype overrides, `preview=True` stores nothing) and `table_to_cells` (never overwrites, 200,000-cell cap).
- **Operations on `data_table` targets**: each in-place operation writes a new version and returns `TableVersionDelta`; `filter` on a sheet range creates a new table (`from_version=0`) and leaves the sheet untouched.
- Golden JSON-Schema files per operation (`tests/golden/`), Persian text for every schema key.

## What does not work yet (honest list; re-read against the code at this commit)
**Contract / integration**
- `ExecContext.table_store()` must return this package's `ParquetTableStore` (the executor needs read/write methods beyond the protocol); any other store gives a typed `not_implemented`. A store must be bound with `.for_owner(user_id)` before `read_page`/`restore_version` (otherwise `owner_unknown`).
- `DataTableTarget` has no `version` field in the contract: a table operation uses the highest existing version and adds a `table_version_assumed` warning when several exist. After an undo (pointer swap) the API must not rely on that.
- `TableSource` (link back to the workbook) is not set by the store (`ExecContext` has no `workbook_id`); apps/api attaches it. `sheet_range_to_table` has no name parameter (default name `Table A1:D4`).
- All versions of one table must live in one directory (resolver contract); there is no compaction API yet (the index supports `compacted`, nothing writes it except pipeline rollback). Concurrent writers to the same table are detected (`version_conflict`) but not locked.

**Pipelines and Tools**
- `join` (needs `extra_targets`) cannot be a pipeline step: `PipelineStep` has no such field (decision: stays out of v1).
- `range` Tool inputs are accepted by no v1 parameter; `validate_tool` cannot know columns created by earlier steps (it checks the first step's literal columns when given a context).
- Each committed step re-reads its input (no in-memory hand-off, see `BENCHMARKS.md`); all steps of a sheet pipeline must agree on `has_header`.
- Rolling back a sheet step writes the `before` values back; a formula removed by a *confirmed* `convert_to_values` step cannot be restored that way. If a rollback is incomplete the result says `rollback_incomplete`.

**Sheet ranges**
- In-place operations refuse ranges with formulas (the `formulas` parameter, `refuse` by default, can be set to `convert_to_values` by the user; undo restores the formula; operations that only read the range, such as filter/group/pivot/unpivot/join, accept formulas and use their values), with error values, and with mixed-type columns; dates arrive only as `DateValue`; number columns are always `Float64`. Results that grow need free cells to the right/below (`would_overwrite`); there is no row/column insertion in v1.
- Two sheet paths with identical results: row-major (`list[list[Cell]]`, about 7 microseconds per cell in the adapter) and, when the context implements the optional `ColumnarExecContext` (contract v0.4.0) and the range has no formulas, columnar (about 0.5 microsecond per cell; the write skips an unchanged header row; operations that change the header still write row-major). `columnar=False` forces the row path. Whether this pays off with the real engine is **not measured** (`BENCHMARKS.md`). With the 200,000-cell cap the largest in-place range is about 10,000 rows x 20 columns.
- `chart_data` reads a sheet source with its first row as header (the spec has no header flag). Analysis operations accept sheet ranges by reading them as an implicit snapshot (the catalog lists tables). `filter` on a sheet range creates a new table.

**Operations**
- `find_replace` has no user regex by design. `computed_column`: `round` rounds to whole numbers only; text comparison is by code point (no Persian collation); `year/month/day` are Gregorian.
- Collation (`sort`, `read_page`, `sort_groups`): no natural-number ordering; Latin case ties keep original order; hamza is placed just after alef (simplified). Not an ICU replacement.
- `convert_calendar`: Jalali years 1300 to 1500 only; outside that range values are reported, never guessed. Datetimes keep only their date part.
- `pivot` is capped at 200 new columns; `join` refuses more than 5,000,000 matching pairs; charts cap at 5,000 categories; unpivot of mixed types converts everything to text (warning).
- Decimal columns are stored as Decimal(38,10) (verified with polars 2.1.0 only). Floating-point sums use Polars' parallel aggregation, so the last bits of very large float sums may differ between machines.
- Tables are read fully into memory for an operation (not tested larger than memory). No DuckDB (ADR-012).

**Performance**: `BENCHMARKS.md` (data tables at 100,000 x 20: 0.04 to 1.0 s per operation on a 1-core VM; sheet ranges measured at 10,000 rows with a test double, no real engine).

## Develop
```
pip install -e ../../contracts/python -e '.[dev]'
pytest -q && ruff check . && mypy src
```
