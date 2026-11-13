# packages/dataops — Data Operations & Analytics

Owner: Agent 2. Brief: [agents/AGENT_2_DATAOPS.md](../../agents/AGENT_2_DATAOPS.md). Plan: [PLAN.md](PLAN.md). Operation list: [docs/OPERATIONS_CATALOG.md](../../docs/OPERATIONS_CATALOG.md). Form vocabulary: [docs/PARAMS_SCHEMA.md](docs/PARAMS_SCHEMA.md).

**Status: M1 (sort, filter, remove_duplicates) — in progress.**

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
- Golden JSON-Schema files per operation (`tests/golden/`), Persian text for every schema key.

## What does not work yet (honest list)
- Operations other than sort/filter/remove_duplicates (find_replace, fill, clean_text, split/merge, change_type, computed_column, group/pivot/join/unpivot, convert_calendar) are not built yet.
- `data_table` targets, `ParquetTableStore`/`create_table_store`, the sheet<->table bridge: M2 (typed `not_implemented` errors until then).
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
