# packages/dataops — Data Operations & Analytics

Owner: Agent 2. Brief: [agents/AGENT_2_DATAOPS.md](../../agents/AGENT_2_DATAOPS.md). Plan: [PLAN.md](PLAN.md). Operation list: [docs/OPERATIONS_CATALOG.md](../../docs/OPERATIONS_CATALOG.md). Form vocabulary: [docs/PARAMS_SCHEMA.md](docs/PARAMS_SCHEMA.md).

**Status: M4 (calculation, analysis, chart data) — in progress.**

## What works (each item is covered by a test in `tests/`)
- `create_executor(config)` returns a `DataOpsExecutor` that satisfies the contract's `OperationExecutor` protocol (`isinstance` check).
- Registry + descriptor generation: JSON Schema from pydantic params, i18n keys for titles/descriptions/enum labels, `x-gridora-*` hints.
- Executor machinery on **sheet-range targets** (proved with test-only operations): schema validation with JSON-pointer paths relative to the Operation root, data-dependent column checks (`validate(op, ctx)`), preview with zero side effects, apply with one `write_range` call and one engine delta, exact undo/redo via the delta, refusal to turn formulas into values, refusal on error values and mixed-type columns, `would_overwrite` instead of silent overwrite, configurable cell cap per patch (`max_patch_cells`, default 200,000).
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
- **`change_type`**: text/number/bool/date/datetime conversions; Persian/Arabic-Indic digits, `٬ ، ,` thousands separators and `٫` decimal separator understood; comma is only a decimal separator when asked (`decimal_separator=comma`); failures stop the operation with a count and examples (or become empty with `on_error=null` and a warning).
- **`ParquetTableStore`** (`create_table_store(path_for)`): immutable zstd Parquet versions written atomically (temp + fsync + hard link, never overwrites), `read_page` with Persian-aware stable sort, `restore_version` as a pointer swap (`version_unavailable` if compacted), per-owner isolation, all contract dtypes round-trip (decimal stored as Decimal(38,10)).
- **Bridge**: `sheet_range_to_table` (explicit `header_row`, whole-number floats become int64, mixed columns become text and error cells empty *with warnings*, dtype overrides, `preview=True` stores nothing) and `table_to_cells` (never overwrites, 200,000-cell cap).
- **Operations on `data_table` targets**: each in-place operation writes a new version and returns `TableVersionDelta`; `filter` on a sheet range creates a new table (`from_version=0`) and leaves the sheet untouched.
- Golden JSON-Schema files per operation (`tests/golden/`), Persian text for every schema key.

## What does not work yet (honest list)
- Not built yet: `convert_calendar`, pipelines (`run_pipeline`) and Tools (`bind_tool`/`validate_tool`) (M5), benchmarks (M5).
- `computed_column`: `round` rounds to a whole number only; text comparisons are plain code-point comparisons (no Persian collation); no Jalali date functions (`year/month/day` are Gregorian).
- Analysis operations take sheet ranges by snapshotting them (the catalog lists tables); floating-point sums use Polars' parallel aggregation, so the last bits of very large float sums are not guaranteed identical across machines with different thread counts.
- `chart_data` reads a sheet source with its first row as header (the spec has no header flag).
- Header-row *detection*: the contract passes `header_row` explicitly, so none is guessed.
- `TableSource` (link back to the workbook) is not set by the store: `ExecContext` has no `workbook_id`; apps/api attaches it.
- `run_pipeline`, `bind_tool`, `validate_tool` (M5) and `chart_data` (M4): typed `not_implemented` errors.
- Persian modules (collation, digits, clean_text, Jalali): M3/M5.
- Collation limits: no natural-number ordering; Latin case ties keep original order (no lowercase-first); hamza is placed just after alef (simplified).
- Sheet frames: columns that mix types (e.g. numbers and text) are refused; error values (`#N/A`) are refused; dates arrive only as `DateValue`. Number columns are always `Float64` on sheets.
- Nothing has been benchmarked at 100k rows through the executor yet (`BENCHMARKS.md` is written at M5).

## Develop
```
pip install -e ../../contracts/python -e '.[dev]'
pytest -q && ruff check . && mypy src
```
