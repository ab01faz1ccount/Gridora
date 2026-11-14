# packages/engine — Workbook Engine & Excel Compatibility

Owner: Agent 1. Brief: [agents/AGENT_1_ENGINE.md](../../agents/AGENT_1_ENGINE.md). Plan: [PLAN.md](PLAN.md).

**Status (E1): CSV path + cell store.** Entry point: `gridora_engine.create_engine(config)`.

What works (tested in `tests/`):
- `import_csv`: encoding detection (BOM, strict UTF-8, Windows-1256 guess, Windows-1252 fallback;
  guesses are reported), delimiter detection, quoted newlines, Persian/Arabic-Indic digit
  normalization, conservative type inference (leading-zero identifiers, leading `+` and numbers
  with more than 15 digits stay text, all reported in `Workbook.compat`).
- `get_cells` (column-chunked typed store), `close`, `export_csv` (UTF-8 with BOM by default;
  Windows-1256 optional; text cells starting with `= + - @ TAB CR` are prefixed with `'` unless
  `csv_neutralize_formulas=False`; reported via the non-contract `last_export_report`, CC-9).
- Excel serial date helpers (1900/1904, serial-60 quirk) and date-format classification
  (not yet wired to cells: styles arrive with XLSX import).
- Typed errors, resource limits, compatibility registry with a CI honesty gate.

What does not work yet (raises `EngineNotImplementedError`): `import_xlsx`, `apply_cell_edits`,
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
