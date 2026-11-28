# INTEGRATION: what `apps/api` must give `gridora_dataops`, and what it gets back

Audience: the platform module (apps/api, apps/web). Status: matches the code at this commit; the Python block in section 3 is **executed by a test**
(`tests/test_integration_doc.py`), so it cannot drift. Contract version 0.4.x.

## 1. The seven things the API must provide (checklist)
1. **`path_for(owner_id, table_id, version) -> Path`**, inside `DATA_ROOT`. **All versions of one table must be in the same directory**
   (dataops keeps a `table.json` index next to them). Dataops never builds a path itself. `StorageLayout.table_path` already has this shape.
2. **One shared store:** `store = create_table_store(path_for)` once at startup, and `ExecContext.table_store()` must return **that same
   instance**. Dataops refuses any other store (`not_implemented`).
3. **An `ExecContext`** per request with `user_id`, `workspace_id`, `read_range`, `write_range`, `table_store()` (already in
   `EngineExecContext`). Semantics dataops relies on: `read_range` returns the **full rectangle** (`Cell | None`, formulas and errors visible);
   `write_range` writes **values only**, **clears every cell of the rectangle that `rows` does not cover**, returns the engine's delta, and raises
   your own typed error above 200,000 cells (see section 5). Optional but a big speed-up: `read_range_columnar` / `write_range_columnar`
   (contract v0.4.0, ADR-014); without them dataops silently uses the row path and gives identical results.
4. **Bind the store before `read_page` / `restore_version`:** the contract methods carry no owner, so call
   `store.for_owner(user_id).read_page(...)`. An unbound store raises `owner_unknown`. (`apply`, `preview`, `sheet_range_to_table`,
   `table_to_cells` take the owner from `ctx.user_id`.)
5. **Always pass the version pointer:** `DataTableTarget(table_id=..., version=<current version from Postgres>)`. Without it dataops uses the
   highest version and adds a `table_version_assumed` warning, which is wrong after an undo.
6. **Store history yourself:** dataops returns deltas; you write the `HistoryEntry`, keep the current-version pointer in Postgres, and move it on undo/redo.
7. **Map errors** with `envelope(code)` (section 5) and enforce `confirm_destructive` (section 4).

## 2. Entry points (the only names you import; only `composition/wiring.py` may import the package)
| Name | Use |
|---|---|
| `create_executor(config)` | the executor. `config` keys, all optional: `max_patch_cells` (default 200000, keep equal to your cap), `columnar_sheets` (True), `pipeline_handoff` (True), `handoff_max_bytes` (536870912) |
| `create_table_store(path_for)` | the Data Table store (Parquet versions) |
| `catalog(locale)` | flat key -> text; serve it at `GET /operations/i18n` (`fa` default; `en` falls back to Persian per key) |
| `executor.describe_all()` | `GET /operations`: descriptors (labels are catalog keys) |
| `search_operations(query, types, locale, limit)` | the "what do you want to do?" box: ranks operations by Persian task phrases (`ops.<type>.keywords` in the catalog) |
| `executor.preview_with_effect(op, ctx, limit)` | preview **and** exact numbers ("۱۲ ردیف حذف می‌شود") |
| `effect_lines`, `apply_label`, `done_label`, `format_number` | the sentences for the panel, the Apply button and the toast (Persian digits by default, `digits="latin"` on request) |
| `executor.validate / apply / run_pipeline / chart_data / bind_tool / validate_tool` | the contract `OperationExecutor` methods |
| `errors.envelope(code)` | `(top-level contract code, detail code)` for any dataops error code |

Catalog keys the UI reads: `ops.<type>.label|description|keywords|example`, `ops.<type>.params.*` (form titles and option labels),
`ops.categories.*`, `errors.<code>.message`, `effects.*`, `columns.unnamed`. `ops.<type>.example` is a JSON string
`{params, before:{columns,rows}, after:{columns,rows}, extra?, types?, caption}` (a test runs every example through the real operation).

## 3. The call sequence (runnable; the test executes this block)
```python integration-test
from pathlib import Path

from gridora_contracts.models import DataTableTarget, Operation, SheetRangeTarget, TableVersionDelta
from gridora_dataops import (
    apply_label, catalog, create_executor, create_table_store, done_label, effect_lines, search_operations,
)
from gridora_dataops.errors import envelope


# --- once, at startup (composition/wiring.py)
def path_for(owner_id: str, table_id: str, version: int) -> Path:
    return DATA_ROOT / "users" / owner_id / "tables" / table_id / f"v{version}.parquet"  # one directory per table


executor = create_executor({"max_patch_cells": 200_000})
store = create_table_store(path_for)  # the SAME instance must come back from ctx.table_store()
ctx = make_ctx(store)                 # per request: your EngineExecContext(engine, handle, user_id=..., workspace_id=..., store=store)

# --- the search box and the catalog
hits = search_operations("تکراری", [d.type for d in executor.describe_all()], "fa")   # [SearchHit(type='remove_duplicates', ...)]
texts = catalog("fa")                                                                   # GET /operations/i18n

# --- preview: the panel shows rows, the sentences and the Apply label
op = Operation(type="remove_duplicates", target=SheetRangeTarget(range=RANGE), params={})
preview, effect = executor.preview_with_effect(op, ctx, 100)           # raises DataOpsError(validation_failed) on bad input
panel = {
    "preview": preview.model_dump(), "effect": effect.model_dump(),
    "lines": effect_lines(effect, "fa"), "apply_label": apply_label(effect, "fa"),
    "confirm": effect.confirm_recommended,
}

# --- apply: errors come back as a result, not as an exception
result = executor.apply(op, ctx)
if result.status == "error":
    errors = [(*envelope(e.code), e.path, e.message) for e in result.errors]  # e.g. ("operation_conflict", "would_overwrite", ...)
    raise SystemExit(errors)
toast = done_label(effect, "fa")                                                # "۱ ردیف حذف شد" (+ your Undo link)
history_delta = result.delta                                                    # store it in the HistoryEntry

# --- a range -> Data Table, then an operation on it with the version pointer, then undo of that step
shrunk = RANGE.model_copy(update={"r1": RANGE.r0 + result.affected.rows})          # the result is shorter now: header + its rows
table = store.sheet_range_to_table(ctx, shrunk, True, name="فروش")             # DataTable (version 1)
tbl_op = Operation(type="sort", target=DataTableTarget(table_id=table.id, version=table.version),
                   params={"keys": [{"column": "نام"}]})
tbl_result = executor.apply(tbl_op, ctx)
assert isinstance(tbl_result.delta, TableVersionDelta)                          # from_version=1, to_version=2
page = store.for_owner(ctx.user_id).read_page(table.id, 0, 50, version=tbl_result.delta.to_version)   # bound store!
undo_to = tbl_result.delta.from_version                                         # undo = move your pointer back ...
restored = store.for_owner(ctx.user_id).restore_version(table.id, undo_to)      # ... and let dataops confirm it still exists
```

## 4. What each call returns, raises, and what you must do with it
| Call | Returns | Raises | You must |
|---|---|---|---|
| `describe_all()` | `OperationDescriptor[]`, sorted by id | nothing | cache; serve at `GET /operations` |
| `validate(op, ctx=None)` | `ValidationError[]` (empty = valid); paths are relative to the Operation (`/params/keys/0/column`) | nothing | pass `ctx` to also check column names |
| `preview` / `preview_with_effect` | `PreviewResult` (+ `EffectSummary`) | `DataOpsError` with `.errors` (code `validation_failed`, or `not_implemented`) | answer 422 with `.errors`; never writes anything |
| `apply(op, ctx)` | `OperationResult`: `status`, `delta`, `affected`, `warnings`, `errors`, `output` (a new table) | **only** errors raised by your own `ExecContext` (they propagate unchanged) | write the `HistoryEntry` from `delta`; map `errors` |
| `run_pipeline(p, target, ctx)` | one `OperationResult` per step, each with its **own** delta; on failure every result has `status="error"` (the failing one has the cause, the rest `pipeline_aborted`) and **nothing is applied** | only your context's own errors (earlier steps are rolled back first) | one history entry per step |
| `bind_tool` / `validate_tool` | `Pipeline` / `ValidationError[]` | `DataOpsError` (bind) | |
| `chart_data(spec, ctx)` | `ChartData` | `DataOpsError` | |
| `store.sheet_range_to_table(..., preview=True)` | `TableImportPreview` (nothing stored); otherwise `DataTable` | `DataOpsError` | |
| `store.table_to_cells(table_id, ctx, anchor, version)` | `Delta` | `DataOpsError` (`would_overwrite`, `too_large_for_history`) | |

**Delta kinds and undo.** `CellPatchDelta` -> the engine's `apply_delta(inverse=True)`. `TableVersionDelta(from, to)`: undo = pointer to `from`,
redo = pointer to `to`; `from_version == 0` means "a table was created": undo hides it, redo shows it. Table versions are immutable files: undo/redo
never recompute anything. If old versions are deleted later, `restore_version` raises `version_unavailable`; use `store.discard_version` /
`discard_table` only to clean up a version you wrote but could not record (see "Transactions").

**`confirm_destructive`.** `API_CONTRACTS.md` requires it for every descriptor with `destructive: true`. Dataops adds a sharper signal:
`effect.confirm_recommended` is true only when something is **lost** (rows removed, cells emptied, columns removed), a formula would become a value,
or the change is large. Recommendation: ask for the extra click when `descriptor.destructive and effect.confirm_recommended`, or when
`effect.formulas_converted > 0`; do not ask for a harmless rewrite such as a small find-and-replace (UX_SPEC principle: confirm only when it matters).
The effect is advice for the screen: undo restores everything inside the history window.

## 5. Errors: dataops code -> HTTP
`envelope(code)` returns `(top-level code, detail code)`; put the second one in `ErrorDetail.code` (the history limit is exactly the one in ADR-015).

| Top-level (HTTP) | Dataops codes (detail) |
|---|---|
| `validation_failed` (400/422 as in API_CONTRACTS) | `unknown_operation`, `unsupported_target`, `invalid_param`, `unknown_param`, `unknown_column`, `type_mismatch`, `mixed_column_types`, `range_has_error_values`, `validation_failed`, `result_too_large`, `chart_too_many_categories`, `chart_series_mismatch`, `chart_too_many_series` |
| `operation_conflict` (409) | `range_has_formulas`, `would_overwrite`, **`too_large_for_history`**, `version_conflict`, `version_unavailable`, `pipeline_aborted`, `rollback_incomplete` |
| `not_found` (404) | `table_not_found` |
| `forbidden` (403) | `owner_unknown` |
| `bad_request` (400) | `not_implemented` |

Messages: `catalog(locale)["errors.<code>.message"]` (Persian, written for a newcomer; `too_large_for_history` is the sentence from UX_SPEC F4).
If your `write_range` raises its own `DomainError` (the 200,000-cell cap) from inside an operation, **do not catch it**: dataops lets it
propagate unchanged and, inside a pipeline, rolls the earlier steps back first.

## 6. Transactions, concurrency, limits
- **Not transactional with Postgres.** Order: `apply` (dataops writes the Parquet version / the cells) -> you record the history entry and move the
  pointer. If recording fails after a table version was written, call `store.for_owner(...).discard_version(owner, table_id, to_version)` for that
  version. Sheet writes go through your engine, so they follow your own transaction.
- **Concurrent writers to one table:** the second writer gets `version_conflict` (409); the version file is created without overwriting, so
  nothing is lost. Retry with a fresh pointer.
- **Threads:** the executor and the store keep no per-request state; calls for different documents may run concurrently. Polars uses its own
  thread pool, so size workers with that in mind (1 core in my measurements: 0.04 to 1.0 s per operation at 100,000 x 20, see `BENCHMARKS.md`).
- **Limits:** 200,000 cells per sheet write (`too_large_for_history`), 5,000,000 matching pairs in a join, 200 pivot columns, 5,000 chart
  categories, 512 MB of planned frames held between pipeline steps. All return typed errors, none crash.
- **Sheets with formulas:** in-place operations refuse them (`range_has_formulas`) unless the form's `formulas` option is `convert_to_values`;
  `filter`, `group_aggregate`, `pivot`, `unpivot`, `join` only read the range and accept formulas.

## 7. What the contract still lacks (CONTRACT_CHANGE proposals; I did not edit `contracts/`)
1. **`PreviewResult.effect` (and `OperationResult.effect`).** Today the numbers travel only through `preview_with_effect`, so the API must build its own
   response envelope (`panel` above). Proposal: `effect: Optional[Effect]` with the fields of `EffectSummary`.
2. **`validate()` cannot carry numbers**, so the "X rows would be removed" text needs a preview call, not a validation call. (Fine; documented.)
3. **`TableStore.read_page` / `restore_version` carry no owner**; `for_owner()` is the workaround. Proposal: an `owner_id` argument.
4. **`PipelineStep` has no `extra_targets`**, so `join` cannot be a pipeline step. **`ToolInput.kind == "range"`** is accepted by no parameter.
5. **Suggestions** (`docs/SUGGESTIONS.md`) would need a new protocol method.

## 8. Things I could not verify
No real engine or real API route called this code; everything above is tested against in-memory doubles that follow the protocols (and the
conformance test `tests/test_contract_conformance.py`). The API's `EngineExecContext` does not implement the columnar methods yet; until it does,
the row path (correct, slower) is used. Persian wording has not been read by a real newcomer.
