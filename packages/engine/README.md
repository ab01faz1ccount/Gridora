# packages/engine — Workbook Engine & Excel Compatibility

Owner: Agent 1. Brief: [agents/AGENT_1_ENGINE.md](../../agents/AGENT_1_ENGINE.md). Plan: [PLAN.md](PLAN.md).

**Status (E6): CSV, XLSX read (lazy), value edits with undo/redo, XLSX/CSV export, hostile-safe package layer.** Entry point: `gridora_engine.create_engine(config)`.

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
  are recorded per sheet and will appear in the export report (E6).
- Limitations: no editing and no export yet; formulas are not evaluated; shared-formula dependents show
  cached values only; column count is a hint from `spans`/`<dimension>`; `numFmt` codes are not exposed
  (ids only); fixtures are generated, **no Excel-produced file has been tested**; whole-sheet reads are slow
  in pure Python (see BENCHMARKS.md).

Edits (`apply_cell_edits`, `apply_delta`; CSV and XLSX workbooks, value edits only):
- A `CellPatchDelta` carries before/after for exactly the edited cells (CC-4 semantics; there are no
  formula dependents to add yet). `apply_delta(inverse=True/False)` restores/re-applies cell contents
  exactly (value, formula text, style id) and never recalculates. Edits are atomic: validation first,
  rollback on any failure (e.g. a cell/memory budget hit midway).
- Rejected with `validation_failed` and a stable `reason`: formulas (`edit.formulas_unsupported`),
  coordinates outside Excel's limits, NaN/infinity, texts over 32,767 characters, more than
  `max_patch_cells` (200,000) cells (`too_large_for_history`), dates in a workbook without a date format
  (`edit.date_needs_format`; otherwise the cell keeps its date style or gets the workbook's first one),
  and **cells that belong to shared or array formulas** (`edit.protected_formula_cell`) until E7 can
  translate them. Overwriting an ordinary formula cell with a value is allowed and undoable.
- Lazy sheets: the 256-row blocks an edit touches are parsed first, and a later full re-parse keeps
  edits. `SheetState.dirty` tracks cells that differ from the imported file (basis of the E6 export);
  typing the original content back makes a cell clean again.
- **Cached results of formulas are not updated** after an edit (no evaluator yet), so dependents show stale values.
- `tests/roundtrip/test_replay_determinism.py` replays deltas on a fresh engine (through JSON) and
  compares full-workbook fingerprints at every step, including full undo/redo.

Stable error identifiers (`GridoraEngineError.code` = contract top-level code; `.reason` = detail code, via `to_detail()`):
- `operation_conflict` / `too_large_for_history`: an edit or delta above `max_patch_cells` (default 200,000). Review 4: apps/api maps `exc.code` to the status and `exc.to_detail()` to the detail, as it already does for dataops.
- `validation_failed` / `edit.protected_formula_cell`: the cell belongs to a shared or array formula (refused until E7). Other edit reasons: `edit.formulas_unsupported`, `edit.out_of_range`, `edit.invalid_number`, `edit.string_too_long`, `edit.date_needs_format`, `delta.out_of_range`, `delta.unsupported_kind`.
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

What does not work yet (raises `EngineNotImplementedError`): `recalculate`. `FormattingEngine`/`StructureEngine` not implemented.

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
Proposed CI: `ci/engine.yml.proposed`.
