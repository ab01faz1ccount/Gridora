# packages/engine — Workbook Engine & Excel Compatibility

Owner: Agent 1. Brief: [agents/AGENT_1_ENGINE.md](../../agents/AGENT_1_ENGINE.md). Plan: [PLAN.md](PLAN.md).

**Status (E4): CSV, XLSX read (lazy), cell store, hostile-safe package layer.** Entry point: `gridora_engine.create_engine(config)`.

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

What does not work yet (raises `EngineNotImplementedError`): `apply_cell_edits`,
`apply_delta`, `recalculate`, `export_xlsx`. `FormattingEngine`/`StructureEngine` not implemented.

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
