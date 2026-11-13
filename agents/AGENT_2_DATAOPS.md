# Agent 2 — Data Operations & Analytics

You work in `packages/dataops/` only. Read first: `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/API_CONTRACTS.md` (§7–10), `docs/MODULE_BOUNDARIES.md`, `contracts/`, `docs/WORKFLOW.md`, `docs/I18N_SPEC.md`.

## Mission
Let non-expert users do powerful data work through graphical controls: every capability is an Operation with a validated parameter schema, a preview, and an inverse.

## Step 0 — Plan first (no code yet)
Submit `packages/dataops/PLAN.md`: operation list and priority, registry design, how deltas/undo work for each operation kind, Polars vs DuckDB split, test plan. Wait for Agent 0 approval.

## Deliverables
1. `OperationExecutor` and `TableStore` implementations (`contracts/python/gridora_contracts/protocols.py`).
2. Operation registry: each op exposes an `OperationDescriptor` with JSON Schema params, `destructive` flag, `supports_preview`. Labels/descriptions are i18n keys, with Persian text in the catalog (Persian-first).
3. Initial operations (in this order): sort, filter, remove duplicates, find/replace, fill down/up, trim/case/clean text, split/merge columns, change type, computed column (GUI expression builder, not free scripting), group & aggregate, pivot, join/merge tables, unpivot.
4. Pipelines and reusable Tools (parameterized pipelines, ADR-007) with validation of input bindings.
5. Data Table store: versioned immutable Parquet; metadata handed back to the API for Postgres; sheet↔table bridge with header detection, dtype inference and user overrides, preview mode.
6. Chart data aggregation: `ChartSpec` + source → `ChartData` (ECharts-independent).
7. Persian awareness: Persian/Arabic digit normalization on request, Arabic vs Persian `ي/ك` → `ی/ک` cleaning operation, Jalali date conversion operation (library choice goes through DECISIONS.md).
8. Performance test at 100k rows for each operation; results in `BENCHMARKS.md`.

## Acceptance criteria
- Every operation has tests for validate, preview, apply, undo/redo (apply inverse delta, state equals original).
- Deterministic results; no hidden global state.
- Destructive ops flagged correctly; previews never mutate.
- Reads/writes sheet data only through `ExecContext`; never imports `packages/engine` or `apps/*`.
- Validation errors use `ValidationError` with JSON-pointer paths.
- New dependencies are justified in `docs/DECISIONS.md` via a PR note to Agent 0.

## Must not modify
`contracts/`, `apps/`, `packages/engine/`, `docs/` (except your own module docs under `packages/dataops/`).
