# Gridora — Project Reference

Everything the module READMEs used to say, in one place: what each part does, how it is built, how to run it, and where its limits are. Design rationale lives in [DECISIONS.md](DECISIONS.md) and the per-module `DESIGN.md` files; measured numbers in [LIMITS.md](LIMITS.md) and the `BENCHMARKS.md` files.

---

## Workbook engine (`packages/engine`)




What works (tested in `tests/`):
- `import_csv`: encoding detection (BOM, strict UTF-8, Windows-1256 guess, Windows-1252 fallback;
  guesses are reported), delimiter detection, quoted newlines, Persian/Arabic-Indic digit
  normalization, conservative type inference (leading-zero identifiers, leading `+` and numbers
  with more than 15 digits stay text, all reported in `Workbook.compat`).
- `get_cells` (column-chunked typed store), `close`, `export_csv` (UTF-8 with BOM by default;
  Windows-1256 optional; text cells starting with `= + - @ TAB CR` are prefixed with `'` unless
  `csv_neutralize_formulas=False`; the `CompatibilityReport` is the return value of `export_csv`, contract v0.3.0 / CC-9).
- Excel serial date helpers (1900/1904, serial-60 quirk) and date-format classification
  (not yet wired to cells: styles arrive with XLSX import).
- Typed errors, resource limits, compatibility registry with a CI honesty gate.

Package layer (internal, `gridora_engine.package`; not yet reachable through `import_xlsx`):
- `SafeZip`: validates entry count (from the EOCD record, before any table is built), names
  (traversal, absolute, backslash, drive letters, NUL, control characters, duplicates, case-fold
  duplicates), encryption flags, compression methods (stored/deflate only), declared sizes and
  ratios, local-header consistency and **overlapping entries**; reads are budgeted by bytes actually
  produced. Nothing is ever extracted to disk.
- `xmlsafe.parse`: expat wrapper that rejects DOCTYPE/entities/external references, non-UTF-8
  encodings and excessive depth; all failures are typed errors with fixed messages.
- `PackageModel`: content types, relationships (external targets recorded, never followed),
  main-document check (xlsx/xlsm/xltx/xltm), and `write_package`: clean parts are streamed from
  the source archive, so unknown parts are byte-for-byte preserved (decompressed content); dirty parts
  are replaced, dropped parts removed. Zip container metadata (timestamps, compression) is not preserved.
- Tested with hostile fixtures generated in the tests; LibreOffice opens round-trip output (secondary oracle only).

XLSX import (`import_xlsx`, read-only so far):
- Opens through the safe package layer, reads workbook structure (sheets incl. hidden/very hidden,
  chart sheets skipped and reported, defined names, 1900/1904 dates), styles (number-format ids,
  date detection) and shared strings (rich text joined to plain text, phonetic runs skipped).
- **Lazy sheets:** each worksheet is spooled to a private temp file and indexed by a byte scan;
  cells are parsed one 256-row block at a time when `get_cells` asks for them. Index hints are
  validated against the safe parse and fall back to a full parse on mismatch.
  Consequence: cell-level problems (a cell outside Excel's limits, an overlong text, the cell/memory
  budgets) surface as typed errors from `get_cells`, not from `import_xlsx`; row-level problems and
  everything outside `<sheetData>` are checked at import.
- `get_cells` returns values (number, text, bool, error, **date** for date-formatted numbers), formula text
  (`Cell.f`, ordinary/array/shared-master formulas only), style id (`s`) and number-format id (`t`).
- `CompatibilityReport` from a registry: preserved parts and sheet-level features with locations,
  supported (RTL view, frozen panes), partial (formulas shown but not recalculated, shared/array
  formulas, rich text, defined names). Anomalies found lazily (invalid values, unmapped error kinds)
  are recorded per sheet and will appear in the export report .
- Limitations: no editing and no export yet; formulas are not evaluated; shared-formula dependents show
  cached values only; column count is a hint from `spans`/`<dimension>`; `numFmt` codes are not exposed
  (ids only); fixtures are generated, **no Excel-produced file has been tested**; whole-sheet reads are slow
  in pure Python (see BENCHMARKS.md).

Edits (`apply_cell_edits`, `apply_delta`; CSV and XLSX workbooks, value edits only):
- A `CellPatchDelta` carries before/after for the edited cells **and every recalculated dependent** (CC-4 semantics); dependents on other sheets are in `others` (contract 0.5.0). `apply_delta(inverse=True/False)` restores/re-applies cell contents
  exactly (value, formula text, style id) and never recalculates. Edits are atomic: validation first,
  rollback on any failure (e.g. a cell/memory budget hit midway).
- Formula text is parsed on entry: a syntax error is `edit.formula_syntax`; a value and a formula together is `edit.value_and_formula`; an unknown function evaluates to `#NAME?`.
- Rejected with `validation_failed` and a stable `reason`:
  coordinates outside Excel's limits, NaN/infinity, texts over 32,767 characters, more than
  `max_patch_cells` (200,000) cells (`too_large_for_history`), dates in a workbook without a date format
  (`edit.date_needs_format`; otherwise the cell keeps its date style or gets the workbook's first one),
  and **cells inside an array formula range or a data table** (`edit.protected_formula_cell`). Members of a shared formula group can be edited (the group is rewritten as plain formulas). Overwriting an ordinary formula cell with a value is allowed and undoable.
- Lazy sheets: the 256-row blocks an edit touches are parsed first, and a later full re-parse keeps
  edits. `SheetState.dirty` tracks cells that differ from the imported file (basis of the export);
  typing the original content back makes a cell clean again.
- **Formulas are recalculated** after edits (see ADR-016 and the Formulas section); cells that cannot be calculated keep their saved result and are reported.
- `tests/roundtrip/test_replay_determinism.py` replays deltas on a fresh engine (through JSON) and
  compares full-workbook fingerprints at every step, including full undo/redo.

**Sheet ids are deterministic** (`uuid5` of file id, position and name): importing the same file again gives the same sheet ids; working-copy (workbook/handle) ids still differ, several copies can be open.

Stable error identifiers (`GridoraEngineError.code` = contract top-level code; `.reason` = detail code, via `to_detail()`):
- `operation_conflict` / `too_large_for_history`: an edit or delta above `max_patch_cells` (default 200,000). apps/api maps `exc.code` to the status and `exc.to_detail()` to the detail, as it already does for dataops.
- `validation_failed` / `edit.protected_formula_cell`: the cell belongs to an array formula or data table. Other edit reasons: `edit.formulas_unsupported`, `edit.out_of_range`, `edit.invalid_number`, `edit.string_too_long`, `edit.date_needs_format`, `delta.out_of_range`, `delta.unsupported_kind`.
- `unsupported_workbook` / `xlsx.legacy_xls` (old binary .xls), `xlsx.encrypted` (password-protected OOXML), `xlsx.encrypted_or_legacy` (other OLE2), `xlsx.strict_ooxml`. Messages are fixed English text; apps should map the reason to a localized message.

Corpus: `tests/corpus/` runs every file in `corpus/` (Apache POI workbooks, the private plain files, the softwiro
payroll workbook, hostile files in a child process with memory/time limits, the `.xls`, the CSV). Cell counts are
checked against an independent oracle, other counts against `corpus/manifest.json`, and any report item the
manifest lists but the report lacks must be explained by an explicit, verified rule.

Export (`export_xlsx`, `export_csv`):
- **XLSX-origin workbooks are patched, not regenerated.** Parts nobody touched are written byte for byte (unknown
  parts included); in an edited sheet everything outside the rows that contain edits is copied from the original
  bytes (prefix, suffix, untouched rows, unedited cells inside a rebuilt row, row attributes; `spans` is
  recomputed); only edited cells are regenerated. `<dimension>` grows only when edits extend the used range.
  Edited text is written as **inline strings** (sharedStrings is not touched; Excel converts them on its next
  save); XML-illegal characters and CR use the `_xHHHH_` convention, and the same escapes are now decoded on import.
- Each rebuilt row is checked for well-formedness, the output is written to `<path>.part` and renamed, and the
  finished file is re-opened with our own reader (never leave a file we cannot open).
- A workbook that was imported from CSV is written as a **new** workbook (one default style, inline strings).
- **The report says what Gridora could not do:** `xlsx.cached_values_stale` when cells were edited and the workbook
  has formulas ("Gridora cannot recalculate formulas ... lists every formula cell": dependencies are not analyzed),
  with `fullCalcOnLoad="1"` set so Excel recalculates on open (`xlsx.full_calc_on_load_set`); `xlsx.calc_chain_dropped`
  when formulas were added/removed (a stale chain makes Excel report corruption); `xlsx.inline_strings`;
  `xlsx.macro_enabled_extension` (the file needs `.xlsm`); edits inside the source of a **preserved** table, pivot
  cache or chart (`xlsx.table.edited_inside`, `xlsx.pivot_table.source_edited`, `xlsx.chart.source_edited`) and
  `xlsx.preserved_parts_not_assessed` for sources given by name; plus anomalies found lazily while reading
  (`xlsx.cell_value_invalid`, `xlsx.error_value.unmapped`).
- **Refused:** edited sheets whose XML layout cannot be patched safely (prefixed element names, non-ascending
  rows, an index the parser rejected) fail with `unsupported_workbook` / `export.sheet_not_patchable`; rewriting
  them from the model would lose shared formulas and rich text. Unedited workbooks of any layout export fine.
- Not done: comments/threaded comments, tables and pivots are kept but never rewritten after edits; sharedStrings
  is never appended; no style edits.

Columnar access (`ColumnarEngine`, contract 0.4.1; `isinstance(engine, ColumnarEngine)` is true):
- `read_range_columnar(wb, rng)`: per column `num`/`str`/`bool`/`date` (ISO)/`empty`, or `mixed` (exact cell-value dicts) when a column holds
  several kinds, errors, or dates next to plain numbers; `has_formulas` is true if any cell in the range has a formula (shared-formula
  dependents included). Same values as `get_cells`, cell by cell (tested on random ranges and on every corpus file). A formula without a
  cached value reads as empty. The range area is bounded by `max_cells`.
- `write_range_columnar(wb, rng, data)`: values only; every cell of the range ends up equal to `data` (`None` clears); only **changed** cells
  are in the returned `CellPatchDelta`; same rules as edits (shared/array formula cells refused, ordinary formulas overwritten and recorded in
  `before`, dates need a date format); all-or-nothing. Up to `max_patch_cells` changed cells the result is a `CellPatchDelta`.
  **Above it, with a `BlobStore` (`create_engine(config, blobs)`), the result is a `RangeSnapshotDelta`** (ADR-014): the exact
  content of the rectangle before and after (values, style ids, formula text) is stored as two blobs and the delta holds only
  their refs and `cell_count` (= changed cells). Without a blob store: `operation_conflict` / `too_large_for_history`.
- `apply_delta` handles `range_snapshot` in both directions; the blobs are decoded, bounds-checked and applied to the store
  with bulk array writes, all columns or none. The blob format (profile R, `model/snapshot.py`) is deterministic, versioned
  (`GRSB`, version 1), zlib-compressed, SHA-256-checked and never executes anything; the decoder validates sizes against
  `ResourceLimits` before allocating and decompresses with a byte budget. A missing, damaged, oversized or newer blob fails with
  `internal_error` / `snapshot.unavailable` | `snapshot.corrupt` | `snapshot.unsupported_version` and **changes nothing**
  (undo never half-applies). A failing blob store on write: `snapshot.store_failed`, nothing changed.
- Export regenerates every cell inside bulk-written rectangles (rows/cells outside stay byte-equal to the file).

Not provided by the engine: `FormattingEngine` (styles are preserved on a round trip but not exposed to the interface) and `StructureEngine` (inserting and deleting rows or columns).

Known limitations:
- CSV dates and booleans stay text (no inference). Leading `+` numbers stay text on purpose.
- Windows-1256 cannot represent Persian yeh (U+06CC), Persian digits or Arabic-Indic digits, so
  exporting such text to Windows-1256 fails with `csv.unencodable_character` instead of silently
  substituting characters (normalization is a dataops operation).
- Neutralizing formula text on export changes round-trips of text such as `+98912...`.
- Handles are not thread-safe; `apps/api` must serialize access per workbook.
- Time limits are cooperative only; hard memory/time isolation is Phase 4 (ADR-011).
- Benchmarks: [BENCHMARKS.md](BENCHMARKS.md) (CSV only so far).

Dev: `pip install -e contracts/python -e "packages/engine[dev]"`, then `ruff check`, `mypy src`, `pytest`.


### Formulas (ADR-016)
- Pure-Python parser/evaluator (`gridora_engine.formula`) and dependency-graph calculator (`gridora_engine.calc`). About 400 functions; unknown ones give `#NAME?` when typed and keep their saved result when imported (reported).
- `Engine.apply_cell_edits` recalculates dependents (same and other sheets) and returns them in the delta; `Engine.recalculate` does a full recalculation. Cycles keep their cached value. `TODAY/NOW/RAND/RANDBETWEEN/INDIRECT/OFFSET` recalculate every time (`engine.now` is a test hook).
- **Calendar:** `create_engine({"calendar": "jalali"})` is the default; `gregorian` and `hijri` are available, and `Engine.set_calendar(handle, mode)` switches and recalculates. `Engine.detect_date_columns(handle, sheet_id)` returns date columns (`kind`: `serial` or `text`, `calendar`, counts). Explicit functions `JYEAR/JMONTH/JDAY/JDATE`, `HYEAR/HMONTH/HDAY/HDATE` ignore the mode.
- Oracle test: `tests/corpus/test_formula_oracle.py` recalculates every corpus formula and compares it with Excel's cached value (the private payroll workbook must match exactly).
- Not done yet: see the known gaps in ADR-016.


---

## Data operations (`packages/dataops`)




### Features
- `create_executor(config)` returns a `DataOpsExecutor` that satisfies the contract's `OperationExecutor` protocol (`isinstance` check).
- Executor on **sheet ranges and data tables** for all 15 operations: schema validation with JSON-pointer paths relative to the Operation root, data-dependent column checks (`validate(op, ctx)`, including `extra_targets` columns), preview with zero side effects, apply with ONE `write_range` call (sheets, one engine delta) or ONE new immutable version (tables, `TableVersionDelta`), exact undo via the delta, refusal to turn formulas into values, `would_overwrite` instead of silent overwrite, configurable per-patch cell cap (`max_patch_cells`, default 200,000, error `too_large_for_history`).
- Registry + descriptor generation: JSON Schema from pydantic params, i18n keys for titles/descriptions/enum labels, `x-gridora-*` hints.
- `catalog(locale)`: Persian text for categories and every error code; English falls back to Persian per key.
- Boundary test: no import of `gridora_engine`/`apps`, no network/process modules, no unreviewed third-party packages.
- Polars-vs-DuckDB spike: Polars was faster on every measured workload at 100k rows (ADR-012).
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

### Known limits
**Contract / integration**
- `ExecContext.table_store()` must return this package's `ParquetTableStore` (the executor needs read/write methods beyond the protocol); any other store gives a typed `not_implemented`. A store must be bound with `.for_owner(user_id)` before `read_page`/`restore_version` (otherwise `owner_unknown`).
- `DataTableTarget` has no `version` field in the contract: a table operation uses the highest existing version and adds a `table_version_assumed` warning when several exist. After an undo (pointer swap) the API must not rely on that.
- `TableSource` (link back to the workbook) is not set by the store (`ExecContext` has no `workbook_id`); apps/api attaches it. `sheet_range_to_table` has no name parameter (default name `Table A1:D4`).
- All versions of one table must live in one directory (resolver contract); there is no compaction API yet (the index supports `compacted`, nothing writes it except pipeline rollback). Concurrent writers to the same table are detected (`version_conflict`) but not locked.

**Pipelines and Tools**
- `join` (needs `extra_targets`) cannot be a pipeline step: `PipelineStep` has no such field (decision: stays out of v1).
- `range` Tool inputs are accepted by no v1 parameter; `validate_tool` cannot know columns created by earlier steps (it checks the first step's literal columns when given a context).
- Between steps the planned frames are handed over in memory (default; `pipeline_handoff=False` or a frame set above `handoff_max_bytes`, 512 MB, falls back to re-reading). Results, deltas, per-step undo and rollback are identical either way (tests run every pipeline both ways). All steps of a sheet pipeline must agree on `has_header`.
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

**For the UI:** `search_operations(query, types)` ranks operations by Persian task phrases (`ops.<type>.keywords`; every operation also has an executable `ops.<type>.example`); `executor.preview_with_effect(op, ctx, limit)` returns the preview plus an `EffectSummary` (rows removed, cells emptied, formulas converted, new table, `confirm_recommended`) and `effect_lines` / `apply_label` / `done_label` write the Persian sentences. Docs: [INTEGRATION.md](INTEGRATION.md) (what the API must provide; its code block is run by a test), [docs/SUGGESTIONS.md](docs/SUGGESTIONS.md) (design only), [docs/COPY_REVIEW.md](docs/COPY_REVIEW.md).

**Errors for the API**: `OperationResult.errors` / `DataOpsError.code` use the dataops codes; `gridora_dataops.errors.envelope(code)` gives `(top-level contract code, detail code)`, e.g. `too_large_for_history` -> `("operation_conflict", "too_large_for_history")` (ADR-015). An error raised by the context itself (the API's own history-cap error) propagates unchanged from `apply`; in a pipeline earlier steps are rolled back first.

**Performance**: `BENCHMARKS.md` (data tables at 100,000 x 20: 0.04 to 1.0 s per operation on a 1-core VM; sheet ranges measured at 10,000 rows with a test double, no real engine).

### Develop
```
pip install -e ../../contracts/python -e '.[dev]'
pytest -q && ruff check . && mypy src
```


---

## HTTP API (`apps/api`)

### HTTP route summary (`/api/v1`)
| Area | Routes |
|---|---|
| Session | `POST /login`, `POST /logout`, `GET /me` |
| Workspaces and files | `GET/POST /workspaces`, `GET/PATCH/DELETE /workspaces/{id}`, `GET/POST /workspaces/{id}/files`, `GET /files/{id}/download`, `POST /files/{id}/open`, `GET /jobs/{id}`, `GET /jobs/{id}/compatibility` |
| Workbooks | `GET /workbooks/{id}`, `GET /workbooks/{id}/compatibility`, `GET /workbooks/{id}/sheets/{sheet_id}/cells`, `PATCH` cells, `POST /workbooks/{id}/save`, `POST /workbooks/{id}/export`, `PUT /workbooks/{id}/calendar` |
| History and operations | `GET /documents/{id}/history`, `POST /documents/{id}/undo`, `POST /documents/{id}/redo`, `GET /operations`, `GET /operations/i18n`, `POST /documents/{id}/operations` and `/preview` |
| Data Tables | `GET/POST /workspaces/{id}/tables`, `POST /tables/from-range`, `GET /tables/{id}`, `GET /tables/{id}/rows`, `POST /tables/{id}/operations` and `/preview`, `POST /tables/{id}/undo`, `/redo`, `GET /tables/{id}/history`, `POST /tables/{id}/to-sheet`, `POST /tables/{id}/export` |
| Charts | `POST /documents/{id}/charts`, `GET /documents/{id}/charts`, `PUT/DELETE /charts/{id}`, `GET /charts/{id}/data` |
| Saved tools | `GET/POST /tools`, `GET/PUT/DELETE /tools/{id}`, `POST /tools/{id}/run` |
| Health | `GET /healthz`, `GET /readyz` (outside `/api/v1`) |

The exact list is the OpenAPI document served by the running API; `docs/API_CONTRACTS.md` is the normative description.




#### Features
- App factory (`gridora_api.main:create_app`), configuration from `GRIDORA_*` environment variables.
- Standard success envelope and error envelope; every response carries `X-Request-ID`.
- One status table for the 13 contract error codes, checked against `gridora_contracts.ERROR_CODES`.
- Request-validation errors return `400 validation_failed` with JSON-pointer paths (not FastAPI's 422).
- Unhandled exceptions return `500 internal_error` with no stack trace or exception text.
- `/healthz` and `/readyz` (outside `/api/v1`, not part of the contract).
- Contract route conformance: routes in the app must be a subset of the route table parsed from
  `docs/API_CONTRACTS.md` (+ the v0.2 additions); the number still unimplemented is reported.

- Auth: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` returning contract `AuthResult`.
  argon2id hashes; server-side sessions (only SHA-256 of the cookie token stored); HttpOnly,
  Secure, SameSite=Strict cookie (`__Host-` prefix); session rotated at login; idle (sliding) and
  absolute expiry; synchronizer CSRF token checked on every mutating route that uses the `auth`
  dependency; Postgres-backed login rate limit (`429` + `Retry-After`); audit log rows for login
  and logout; operator CLI (`python -m gridora_api.cli create-user | reset-password | check-config`);
  optional first-start bootstrap admin from env.
- Alembic migration `0001` (users, sessions, login_attempts, audit_log); a test fails if models and
  migrations diverge.
- Isolation harness: every `/api/v1` route with an id parameter must have an isolation case
  (registry is empty until owned resources are added).

- Workspaces and files: workspace CRUD (delete needs `?confirm=true`, removes rows and
  stored bytes), file list, streaming multipart upload, download. Owner-scoped repositories
  (`db/repos/owned.py`: no fetch-by-id-alone exists; another user's id is `404`, same as missing).
- Upload: streamed to quarantine, never buffered; `file_too_large` the moment the file part
  passes the cap (exactly 100 MiB passes, +1 byte fails; tested at the real default with a streamed
  body); early reject on a large `Content-Length`; extension allowlist (`.xlsx .xlsm .csv`) plus
  magic-byte check (`415`); truncated or multi-file bodies are `400` and leave nothing behind;
  display names are sanitized and never used in paths.
- Storage: only `storage/layout.py` builds paths (UUID components + allowlists); files are `0600`,
  placed by temp+fsync+rename and never overwritten; `PathResolver` for dataops is implemented there.
- Isolation: the OpenAPI-driven harness now covers all 6 id routes (404 for another user, 401
  without a session, nothing changed). A test client scans every JSON body and every header of
  every response in the suite and fails the test on any server path or storage detail.

- Composition: `composition/wiring.py` is the only module that loads `gridora_engine` /
  `gridora_dataops` (lazily, through the four fixed factories of contracts v0.2; a test enforces
  that nothing else in the package imports or names them). `GRIDORA_ENGINE` / `GRIDORA_DATAOPS` =
  `stub|real`, one setting each; `real` without the package fails at startup with a clear message;
  a missing factory or an object that does not satisfy the protocol is refused. `PathResolver` is
  handed to `create_table_store`. `FormattingEngine` / `StructureEngine` are feature-detected.
- `EngineExecContext`: typed `read_range` (tiled beyond the 1000 x 100 window cap), value-only
  `write_range` that clears uncovered cells in one delta, 200,000-cell cap per undoable step
  (`operation_conflict` with detail code `too_large_for_history`).
- **STUBS (clearly marked, not real implementations):**
  - `StubEngine`: in-memory (raw values ~150 B/cell; a window read costs the window, not the sheet), single sheet, **CSV only** (UTF-8 with/without BOM, Windows-1256,
    delimiter sniffing). XLSX import/export raise `unsupported_workbook`. `export_csv` returns a `CompatibilityReport` (contract v0.3.0): text that would run as a formula in a spreadsheet (leading `= + - @`, tab, CR) is prefixed with an apostrophe and each such cell is reported with its location; numbers are never touched. Formulas are **not**
    evaluated or stored (a formula edit is rejected with a JSON-pointer error; text that looks like a
    formula stays text). No styles. Every import reports a `partial` compatibility item.
  - `StubExecutor`: `sort`, `find_replace`, `remove_duplicates` on sheet ranges (real JSON-Schema
    params, validate/preview/apply with undoable deltas, `range_has_formulas` refusal, pipelines with
    one delta per step, `bind_tool`). No Persian-aware collation. `StubTableStore` and `chart_data`
    answer `bad_request` ("needs the real dataops package").
  - Visible at runtime: every response carries `X-Gridora-Engine` / `X-Gridora-Dataops`;
    `/readyz` lists `implementations`.

- Jobs and workbooks: `jobs` table + in-process dispatcher (`jobs/runner.py`,
  `PostgresJobRunner` behind a `JobRunner` interface). Claims with `FOR UPDATE SKIP LOCKED` (two
  dispatchers never run the same job: tested with 30 jobs); concurrency cap; jobs left `running` by a
  dead process are failed at startup (not retried), queued ones run; failures are recorded as
  contract `ApiError` (internal crashes are generic, no internals). `GET /jobs/{id}`.
- Upload now queues an `import` job (`job_id` is real). The import runs in a worker thread with a
  time limit; the job result is the workbook id. `POST /files/{id}/open` (idempotent),
  `GET /workbooks/{id}`, `GET /workbooks/{id}/compatibility`, and `GET .../sheets/{sheet_id}/cells`
  (window caps 1000 x 100 enforced, lower configured caps win; empty windows are not errors).
- Working copies (`services/working_copies.py`): LRU cap (`GRIDORA_MAX_OPEN_WORKBOOKS`), per-document
  threading lock around every engine call (handles are not thread-safe), eviction closes the handle,
  a cache miss rebuilds the copy from the stored file (tested: restart/eviction gives identical cells
  and the same sheet ids). Workspace delete drops copies, documents and workbooks.
- The API owns identity: `Workbook.id` is the document id, `file_id` the stored original, `name` the
  user's display name.

- Upload memory (measured in `deploy/`): a 100 MiB upload through nginx costs ~+5 MB of API peak RSS (streamed to disk). A regression test pins the fix for `check_magic`, which used to read the whole file to look at 8 KiB. The *import* is a different matter: the stub engine holds the whole sheet in memory (a 100 MiB CSV used ~670 MB before the storage rewrite; see `deploy/README.md` / PR for current numbers), the real engine's lazy reader is the maintainers' E4 target.

- **Cell edits, undo/redo, history **: `PATCH .../cells` (one request = one atomic history entry),
  `GET /documents/{id}/history` (paged, newest first), `POST .../undo`, `POST .../redo`; responses are the
  contract `CellsChangedResult`. Alembic 0004. Every mutation holds a row lock on the workbook inside one
  transaction, so edits, operations and undo never interleave (6 simultaneous edits with the same `base_seq`:
  exactly one wins); `base_seq` is checked under that lock (`409 version_conflict`, detail `history.stale`);
  `seq` comes from a counter that never goes backwards (a stale client can never mistake a different entry
  for the one it saw). If anything fails after the engine changed, the working copy is dropped and rebuilt
  from the stored file + committed history, so memory never disagrees with the DB.
- **Rebuild = file + history replay**, with a public<->engine **sheet-id map** (see "Real engine" below).
- **Operations as jobs**: `GET /operations`, `GET /operations/i18n`, `POST /documents/{id}/operations/preview`,
  `POST /documents/{id}/operations`. Applying is ALWAYS an `operation` job: the request waits
  `GRIDORA_OPERATION_INLINE_SECONDS` (default 2 s); a fast operation answers `200 CellsChangedResult` like a
  cell edit, a slow one answers `202` + the job (the job's `result_ref` is the history `seq` it created), so
  no request is held open for a heavy operation. Destructive operations need `confirm_destructive` (`409
  operation_conflict`, detail `operation.confirm_required`); EVERY target, including `extra_targets`, is
  checked to belong to the user (`404` otherwise); validation errors are JSON pointers relative to the
  Operation; a change that would not fit the 200,000-cell undo cap fails with `operation_conflict` + detail
  `too_large_for_history` and changes nothing. Progress: none (the executor protocol has no progress hook; CC-13).
- **Real engine** (`GRIDORA_ENGINE=real`, `packages/engine` installed): `create_engine(config, blobs)` with a
  content-addressed, owner-agnostic file `BlobStore`; engine errors (recognised by `code/reason/public_message`,
  no import of the engine outside `composition/wiring.py`) are translated to `DomainError` with the engine's
  stable reason as detail code; `too_large_for_history` is always top-level `operation_conflict`.
  The same HTTP tests (upload, window, edit, undo/redo, concurrency, rebuild) run on the **stub and the
  real engine**; one more reads a real corpus XLSX, edits, undoes and rebuilds it.

#### Working copies and ids
- Sheet ids are deterministic in the engine (`uuid5` of file id, position and name). The API additionally keeps a public-to-engine sheet-id map per working copy (by sheet position) and translates on every call, so URLs and stored history deltas keep working after a restart, eviction or rebuild.
- Sheet dimensions only grow (an edit past the end grows them; undo does not shrink them). History is capped at 5,000 entries until saving can compact it. Deltas are stored as JSONB (no blob spill-over).

#### Known limits
- No `pipelines/run` route: a saved tool is the unit that runs a pipeline (`POST /tools/{id}/run`).
- Import time limit stops *waiting*; the worker thread itself cannot be killed (ADR-011, Phase 4).
- With the stub engine, XLSX uploads are stored but their import job fails with
  `unsupported_workbook`. `POST .../files` returns `job_id: null` until the
  import job exists. The file is stored but not parsed or validated beyond type/magic.
- Lists are not paginated (capped at 1000 rows).
- Only `.xlsx`, `.xlsm`, `.csv` are accepted; UTF-16 CSV is refused (needs a NUL-free text file).
- Rate limiting counts per username and per IP; behind nginx set `GRIDORA_TRUST_PROXY_HEADERS=true`.
- `POST /auth/logout` returns `204` with no body (the contract does not define a response).
- Admin role exists but nothing uses it yet; there are no HTTP admin endpoints (decision recorded in DECISIONS.md).
- The 405 response keeps status 405 with code `bad_request` (the contract has no 405 code).

#### Deviations from the design notes
- Routers import `db.repos` / `db.models` (owner-scoped repositories) instead of going through a
  service layer for plain CRUD. The plan's "routers may not import db/" rule is not enforced; the
  isolation matrix and the repository design are the actual guarantees.

#### Known limits
- Single API worker process (working copies will live in memory). No horizontal scaling.
- No OS-level isolation for hostile-file parsing in v1 (ADR-011); relies on engine limits. Phase 4.

### Pinned tooling
`ruff`, `mypy`, `pytest`, `pytest-asyncio`, `httpx` and `psycopg2-binary` are pinned to exact versions in
`pyproject.toml` (`[dev]`), and `requirements.lock` pins the whole dev environment (runtime + dev, from a
clean venv). `requirements.runtime.lock` pins only what the Docker image installs. Bump a tool in its own
PR: update `pyproject.toml`, regenerate the lock, re-run `ruff`/`mypy`/`pytest`, fix what the new version
reports. The web app already pins every dependency exactly (`package.json` + `package-lock.json`).

### Development
```bash
pip install -e ../../contracts/python
pip install -e ".[dev]"
pytest
ruff check . && mypy src
# tests need PostgreSQL: GRIDORA_TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host/db_test
GRIDORA_DATA_ROOT=./data uvicorn --factory gridora_api.main:run --reload
```


---

## Web app (`apps/web`)


through the `@contracts` alias (never copied).


#### Features
- Vite + React 19 + TypeScript (strict, `noUncheckedIndexedAccess`). `npm run check` = typecheck + lint + tests.
- **API client** (`src/api/client.ts`): unwraps the success envelope; every failure becomes an
  `ApiError` (code, status, request id, `Retry-After`); CSRF header on mutating calls only; dropped
  connection -> `network`; non-JSON body -> `internal_error`; a 401 outside the sign-in calls reports
  "session gone". Server message text is never shown to users: errors map to catalog keys.
- **Sign-in / sign-out / session restore** via `AuthResult` (`/auth/login`, `/auth/me`, `/auth/logout`);
  the CSRF token lives in memory only. Wrong password and rate-limit (with wait time) have their own
  localized messages.
- **Workspaces**: list, create, rename (dialog), delete (confirm dialog; sends `?confirm=true`).
- **i18n**: `fa.json` / `en.json` with compile-time key parity, placeholder-parity test, a message for
  every contract error code. Persian + RTL by default; the language switch flips `lang`/`dir`.
- **Display preferences** (client-side, `localStorage` guarded for blocked/corrupt storage): language,
  digit set (Latin / Persian / Arabic-Indic), calendar (Gregorian / Jalali via `Intl`). Wire and stored
  values stay Latin; `normalizeNumericInput` accepts Persian/Arabic digits and separators but never
  rewrites formulas, digits inside words, or ambiguous input like `1,5`.
- **Fonts**: Vazirmatn (SIL OFL 1.1, license shipped in `public/fonts/OFL.txt`), bundled, no CDN.
- **RTL**: CSS uses logical properties only; a test fails on any physical left/right/width/height.
- **No hard-coded UI text**: a TypeScript-AST test fails on literal text or `title/placeholder/aria-label`
  strings in components (and the scanner itself is tested).
- **Accessibility basics**: labelled form fields, `role=alert` errors, modal dialogs with focus trap,
  Escape to close and focus restored to the opener.
- **Stub badge**: shown only when the server reports `X-Gridora-Engine/Dataops: stub`.
- `vite build` succeeds (~86 kB gzip JS).

#### Grid
- Route `/workbooks/<id>`: sheet tabs and a virtualized, DOM-based grid; `src/grid/`.
- **Windowing**: only visible rows/columns (+ overscan) are rendered (a 100,000-row sheet renders ~280-360
  cells). Cells arrive in 100 x 26 blocks (`BlockCache`): de-duplicated, nearest-first, max 4 in flight, aborted
  when scrolled away, LRU-bounded, failed blocks retried after 3 s. Requests never exceed the 1000 x 100 cap.
- **Excel-sized sheets**: the scroll proxy is capped at 10,000,000 px and scrolled with a scale factor
  (Firefox 160 lays out 10 M px but not 30 M px: measured). Verified in a real browser on 1,048,000 rows.
- **RTL**: the *sheet's* direction (`SheetMeta.rtl`), not the UI language, decides column order and arrows:
  in an RTL sheet column A is at the right and ArrowLeft goes to the next column; Tab/Enter follow reading order.
  Layout uses logical positions (`inset-inline-start`), RTL `scrollLeft` (<= 0) is handled.
- Keyboard (arrows, Shift+arrows, Home/End, Ctrl+Home/End, PageUp/Down, Tab, Enter), click and drag selection,
  ARIA grid roles (`aria-rowcount/colcount`, `aria-activedescendant`, rows/columnheaders).
- Raw values only: numbers use the chosen digit set, strings are bidi-isolated, booleans localized. **Styles and
  number formats are not applied** (no contract exposes them yet).

**Real-browser measurements** (headless Firefox 160, 1 CPU / 4 GB / software rendering, real nginx + API (stub
engine) + PostgreSQL; scripts in `e2e/`, not asserted by CI):

| Check | Result |
|---|---|
| 100,000 x 20 sheet, first data cell after navigation | 0.33 s |
| rendered cells (initial / after jumping to the middle / to the bottom) | 279 / 360 / 279 |
| jump to the middle / bottom until populated | 0.19 s / 0.34 s |
| continuous scroll, ~2000 rows in 4 s | frame p50 33 ms, p95 50 ms, max 84 ms; 12 of 133 frames > 50 ms; 19 `/cells` requests; no cell left unloaded after settling |
| 1,048,000 rows | scroller height accepted (10,000,028 px); 0/25/50/75/100 % show the right rows; last row reachable; frame p95 50 ms |
| RTL layout and keys (4-column RTL sheet) | A right of B, row headers at the right edge, ArrowLeft = next column, ArrowRight = previous, Tab next, Home/End |
A screenshot of the RTL grid is in `e2e/screenshots/`. These are measurements on one slow machine, not budgets.
Frame times are dominated by React re-rendering ~300 cells per scroll step; they are fine here but have not been
tuned, and 60 fps is **not** claimed.

#### Import UI and workbook shell (docs/UX_SPEC.md F1)
- Workspace page `/workspaces/<id>`: drop zone (+ file chooser), file list, one card per import. Upload uses XHR
  (progress, cancel, CSRF); `.xls` and files over 100 MB are refused **before** sending; the job is polled (0.5 s -> 2 s),
  "this may take a minute" after 5 s, remembered by job id so polling resumes after a reload; done -> "Opened" or
  "Opened. N items need your attention" (items not fully supported) with Open / See report.
- Failures give plain Persian advice, never a code: legacy `.xls`, encrypted, strict OOXML, macro extension, stub-only CSV,
  too large, network; the "too large to undo -> convert to a Data Table" message (F4) is the exact spec sentence.
- Compatibility report panel: groups unsupported / partial / supported, per item the code, location, "kept in file",
  "editable"; the engine's English text is shown as given and labelled as such.
- Workbook shell regions: top bar, formula bar (address + raw value, editable), grid, side-panel host (report), sheet tabs, status bar
  (count/sum/average of the selection, flagged "loaded cells only" when not everything is loaded).
- 152 vitest tests pass; tsc strict and eslint clean.

#### Cell editing and undo/redo
- Start editing by typing (replaces the content), F2 or double click (keeps it), or in the value bar above the grid. Enter saves and
  moves down, Tab saves and moves right, Escape cancels, clicking elsewhere saves. A text that is unchanged sends nothing.
- Delete/Backspace clears the selected range (one undo step, at most 50,000 cells). Ctrl+Z undoes; Ctrl+Y or Ctrl+Shift+Z redoes
  (by physical key, so it works on a Persian layout). The toolbar buttons do the same and are enabled from the real history.
- What is typed becomes: `=...` formula; `'text` text (apostrophe dropped); TRUE/FALSE boolean; a number (Persian/Arabic digits and
  separators accepted, sent as Latin); anything else text. Dates, percentages and currencies are NOT recognized yet: they stay text.
- `grid/editing.ts` (`WorkbookEditor`): one per open workbook; requests are serialized, each sends the previous entry's seq as
  `base_seq`; the returned `cells` and `others` are written into the block cache of the sheet they belong to (caches are kept per
  sheet while the workbook is open). A change that arrives while a block is still loading is applied when the block lands.
  On `version_conflict` the history and caches are reloaded and the error is shown. The save indicator shows saving / saved / not saved.
- Clipboard (`grid/clipboard.ts`): Ctrl+C copies the selected VALUES (a formula's result; Latin digits) as tab-separated text, with
  quotes where Excel quotes. It refuses, with a message, when some selected cells are not loaded yet or there are more than 50,000.
  Ctrl+V pastes at the top-left of the selection as ONE change (one undo step), typing each cell like the keyboard would (numbers,
  `=formulas`, text); empty pasted cells clear their target; one value pasted into a bigger selection fills it. Ctrl+X copies and clears
  at once (undo brings it back). Formulas are pasted as typed: references are NOT shifted. Dates arrive as text.
- History panel (top bar "History"): newest first, undone entries dimmed, "show older changes" pages by seq. Cell edits are
  described in the person's language; operation names come from the server and are shown as given.
- Conflict banner: when the server answers `version_conflict` the history and caches are reloaded, the last change is NOT saved, and a
  banner (not only a toast) says so until it is dismissed or the next change succeeds.
- The grid is shown padded: at least 100 rows x 26 columns, and always 20 rows / 5 columns bigger than the data, so empty cells
  outside the data can be typed into (the server answers empty windows there). Ctrl+End still goes to the last cell with data.
- Verified in a real browser on the real engine: `e2e/real_stack.py` (28 checks, see `e2e/README.md`).
- Known limits: the first keystroke of an IME composition (`key` = "Process") cannot open the editor; use F2 or double click.
  The screen updates when the server answers (no optimistic display). Editing a date cell and saving without changes is a no-op, but
  changing it makes text. No fill handle, no formatted (HTML) clipboard.

#### Known limits of the interface
- Find is disabled. Cancelling a running import is impossible (no API; the card says so).
- The task bar and the operation panel, Data Table views, charts, saved tools and export screens are not in the interface yet; the API for all of them exists.
- Keyboard help and an accessibility audit with a screen reader have not been done.

#### Known limits
- Frozen panes, column resize, fill handle and a formatted (HTML) clipboard are not built.
- Screen-reader behaviour of the grid was not tested with a screen reader; row headers are `aria-hidden`.
- Unit/component tests run in jsdom; real-browser checks exist only as the manual `e2e/` scripts (Firefox only; Chrome and Safari were not tested). CSP with the production bundle and font loading were seen working in the native-stack run, not in CI.
- Display preferences are not stored on the server.

### Development
```bash
npm ci
npm run dev     # http://localhost:5173, proxies /api to http://localhost:8000
npm run check
```


---

## Deployment (`deploy/`)




```bash
cd deploy
cp .env.example .env            # set POSTGRES_PASSWORD (letters/digits) and the first admin
./scripts/make-dev-cert.sh      # self-signed, local trials only; real certificates: see TLS.md
docker compose up -d --build
docker compose ps               # wait until api, nginx, postgres are "healthy"
BASE_URL=https://localhost SMOKE_USER=admin SMOKE_PASSWORD='...' CURL_OPTS=-k ./scripts/smoke.sh
```
Then remove `GRIDORA_BOOTSTRAP_ADMIN_*` from `.env` and `docker compose up -d` again.
The compose file now defaults to `GRIDORA_ENGINE=real` and `GRIDORA_DATAOPS=real` (CSV, XLSX, formulas). Set them to `stub`
only for a quick look: then it is CSV only, formulas are not evaluated and the web app shows a "stub engine" badge.
Measured limits and timings: [`../docs/LIMITS.md`](../docs/LIMITS.md).

### What is here
| Piece | Notes |
|---|---|
| `docker-compose.yml` | 4 services. Only nginx is on the `edge` network; `api`, `postgres`, `backup` are on an `internal: true` network, so they cannot reach the outside. Non-root, `cap_drop: ALL`, `no-new-privileges`, read-only root filesystems (+ `/tmp` tmpfs). No port except nginx's is published. Compose refuses to start without `POSTGRES_PASSWORD`. |
| `api.Dockerfile` | Multi-stage, installs `packages/engine` and `packages/dataops` next to the API (the real engine needs them; `polars` is in the lock), runtime dependencies from `apps/api/requirements.runtime.lock` (no dev tools), uid 10001. Entry point runs `alembic upgrade head` (serialized by a Postgres advisory lock), then **one** uvicorn worker. |
| `web.Dockerfile` | Builds the web bundle, serves it with non-root `nginx-unprivileged` (8080/8443 inside, mapped to 80/443). |
| `nginx/` | TLS 1.2/1.3; HTTP→HTTPS 308; strict CSP and other security headers on the static app (CSP: `default-src 'self'`, no inline script or style); `/api/` proxy with HSTS; login throttle (10/min per IP, second layer); uploads up to 101 MiB **streamed** (`proxy_request_buffering off`); `413`/`429`/`5xx` generated by nginx use the API's JSON error envelope; `X-Request-ID` and `X-Real-IP` are set by nginx and overwrite anything the client sent. |
| `backup/` | `backup.sh` (Postgres custom-format dump **then** a hard-link `rsync` snapshot of the stored files, manifest with SHA-256, retention), `restore.sh` (refuses without `--yes`, verifies the dump checksum, restores DB, copies files in additively, then checks every file the DB references exists), daily scheduler. |
| `scripts/smoke.sh` | curl-only end-to-end check of a running stack: headers, SPA fallback, error envelope, 413 from nginx, sign in → workspace → CSV upload → import job → workbook → grid window (Persian text and a typed number) → cleanup. |
| `scripts/test-backup-restore.sh` | Runs backup/restore against a scratch database and folders. |
| `RUNBOOK.md`, `TLS.md` | Operations: first start, backup, restore, upgrade, logs. TLS options. |

### Verification
Run in the development sandbox, **without Docker images** (the sandbox cannot reach any container registry):

| Check | Result |
|---|---|
| `docker compose config` on the compose file | passes; missing `POSTGRES_PASSWORD` fails loudly |
| `nginx -t` with the real `nginx.conf` + `gridora.conf` | passes (nginx 1.24 locally; the single line `http2 on;`, which needs nginx ≥ 1.25.1 as in the image, was removed for the local run) |
| **Native stack**: real nginx with these config files in front of real uvicorn + PostgreSQL 16 (`GRIDORA_ENV=prod`, secure cookies, `trust_proxy_headers`), then `scripts/smoke.sh` | **SMOKE OK**, 27 checks |
| Upload limits through that stack: exactly 100 MiB → `201`; 100 MiB + 1 byte → `413` JSON from the API; 102 MiB → `413` JSON from nginx; no quarantine leftovers | pass |
| API memory during a 100 MiB upload (peak RSS) | +4.6 MB (143.6 MB → 148.2 MB). Before fixing `check_magic` (it read the whole file to look at 8 KiB) the same upload cost about +100 MB |
| `scripts/test-backup-restore.sh` against PostgreSQL 16 | **BACKUP/RESTORE OK**, 16 checks: dump + snapshot + manifest, quarantine excluded, hard-links, restore, tampered dump refused (exit 3), missing file reported (exit 4), retention |

Also run natively (no Docker) with the real engine: restart durability, a full backup → restore drill on live data, a clean-venv install of the runtime lock + both packages followed by starting the API, and the 100,000-row performance run (`apps/web/e2e/perf_real.py`, numbers in `docs/LIMITS.md`).

**Checked by the CI workflow `deploy-stack` (not by hand):**
- `docker build` of the images and `docker compose up` (tags such as `python:3.12-slim`, `node:22-alpine`, `nginxinc/nginx-unprivileged:1.27-alpine`, `postgres:16-alpine` are not pinned by digest). Dockerfile syntax and base-image tags (`python:3.12-slim`, `node:22-alpine`, `nginxinc/nginx-unprivileged:1.27-alpine`, `postgres:16-alpine`) are unchecked; tags are not pinned by digest.
- That the containers really start read-only/non-root, that `internal: true` really blocks egress, healthchecks, the backup container, file ownership between the `api` and `backup` uids on the shared volume.
- Anything over HTTP/2. Behaviour with a browser (CSP with the built bundle, font loading, cookies).
- Air-gapped **builds** (the build needs PyPI, npm and image registries; vendoring is a Phase 4 item). Runtime needs no outbound network by design.
- Restore from an off-host backup; Postgres major-version upgrades.

`.github/workflows/deploy-stack.yml` runs the real check on every relevant pull request (build, `up --wait`, smoke test, egress probes, non-root check, backup and restore).

### Known limits
- **One API worker, open workbooks in memory** (`apps/api/README.md`): no horizontal scaling.
- DB dump and file snapshot are two steps, not one atomic snapshot (DB first). A file deleted by a user in the seconds between the steps would be reported as missing by `restore.sh`, not hidden.
- Backups go to a named volume on the same host by default. That is **not** a backup against disk loss: bind-mount another disk or ship the folder off-host (RUNBOOK.md).
- `.env` holds secrets in clear text; protect it (mode 600). `POSTGRES_PASSWORD` is placed in a URL: use letters and digits.
- The HTTP→HTTPS redirect assumes the public HTTPS port is 443.

