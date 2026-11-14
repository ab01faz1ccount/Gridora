# packages/dataops — Data Operations & Analytics

Owner: Agent 2. Brief: [agents/AGENT_2_DATAOPS.md](../../agents/AGENT_2_DATAOPS.md). Plan: [PLAN.md](PLAN.md). Operation list: [docs/OPERATIONS_CATALOG.md](../../docs/OPERATIONS_CATALOG.md). Form vocabulary: [docs/PARAMS_SCHEMA.md](docs/PARAMS_SCHEMA.md).

**Status: M0 (skeleton) — in progress. No user-facing operation exists yet.**

## What works (each item is covered by a test in `tests/`)
- `create_executor(config)` returns a `DataOpsExecutor` that satisfies the contract's `OperationExecutor` protocol (`isinstance` check).
- Registry + descriptor generation: JSON Schema from pydantic params, i18n keys for titles/descriptions/enum labels, `x-gridora-*` hints.
- Executor machinery on **sheet-range targets** (proved with test-only operations): schema validation with JSON-pointer paths relative to the Operation root, data-dependent column checks (`validate(op, ctx)`), preview with zero side effects, apply with one `write_range` call and one engine delta, exact undo/redo via the delta, refusal to turn formulas into values, refusal on error values and mixed-type columns, `would_overwrite` instead of silent overwrite, configurable cell cap per patch (`max_patch_cells`, default 200,000).
- `catalog(locale)`: Persian text for categories and every error code; English falls back to Persian per key.
- Boundary test: no import of `gridora_engine`/`apps`, no network/process modules, no unreviewed third-party packages.
- Polars-vs-DuckDB spike with measured numbers: `spikes/SPIKE_REPORT.md`.

## What does not work yet (honest list)
- The production registry is **empty**: sort, filter, remove_duplicates and all other operations start in M1.
- `data_table` targets, `ParquetTableStore`/`create_table_store`, the sheet<->table bridge: M2 (typed `not_implemented` errors until then).
- `run_pipeline`, `bind_tool`, `validate_tool` (M5) and `chart_data` (M4): typed `not_implemented` errors.
- Persian modules (collation, digits, clean_text, Jalali): M3/M5.
- Sheet frames: columns that mix types (e.g. numbers and text) are refused; error values (`#N/A`) are refused; dates arrive only as `DateValue`. Number columns are always `Float64` on sheets.
- Nothing has been benchmarked at 100k rows through the executor yet (`BENCHMARKS.md` does not exist until the first operations land).

## Develop
```
pip install -e ../../contracts/python -e '.[dev]'
pytest -q && ruff check . && mypy src
```
