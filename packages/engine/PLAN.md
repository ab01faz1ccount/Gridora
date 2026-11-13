# packages/engine — Implementation Plan (Step 0)

Owner: Agent 1. Status: **proposal, awaiting Agent 0 review.** This document describes intent only. Nothing here is implemented, and no statement below should be read as "supported" or "working".

Scope reminder: I touch `packages/engine/` only. I do not import `packages/dataops` or `apps/*`, I do not edit `contracts/`, and I do not copy external code (see §14 and §18).

---

## 1. Goals and non-goals

**Goals (from `agents/AGENT_1_ENGINE.md`)**
- Implement `WorkbookEngine` (`contracts/python/gridora_contracts/protocols.py`): open XLSX/CSV, serve cell windows, apply edits as deltas, recalculate a documented formula subset, export XLSX/CSV.
- Own an OOXML *package* layer that preserves everything it does not understand, byte-for-byte, and only regenerates parts it changed.
- Generate every `CompatibilityReport` from a versioned feature registry; nothing is dropped silently.
- Persian-first details: RTL sheet view flag, Windows-1256 / UTF-8 CSV, Persian digits, Persian sheet names.
- Reject hostile input safely with typed errors.

**Non-goals for the first implementation PRs**
- Pivot tables, charts, drawings, VBA, external links, slicers, threaded comments: *preserved*, not edited, not evaluated.
- Dynamic arrays / spill, LAMBDA, LET, Power Query, data model: preserved cached values only.
- Structure editing (insert/delete rows or columns, sheet add/rename/delete) — the contract has no method for it yet (see §17, CC-5).
- Any claim of "full Excel compatibility".

---

## 2. Module layout

Python package `gridora_engine` under `packages/engine/src/`, stdlib-only at runtime apart from `pydantic` (already pulled in by `contracts/`).

```
packages/engine/
  PLAN.md  README.md  SPIKE_REPORT.md (Step 1)  BENCHMARKS.md (later)
  pyproject.toml
  src/gridora_engine/
    __init__.py            # exports GridoraEngine only
    engine.py              # WorkbookEngine implementation; handle registry; thin orchestration
    errors.py              # typed exceptions, stable codes (see §11)
    limits.py              # ResourceLimits dataclass + cooperative deadline checks
    model/
      workbook.py          # in-memory Workbook, sheet registry, defined names
      sheet.py             # Sheet + SheetStore interface; columnar store implementation
      values.py            # CellValue <-> internal tagged storage; error mapping
      dates.py             # serial <-> ISO, 1900/1904, number-format date classification
      styles.py            # read-only style table (number formats, style ids)
      deltas.py            # build/apply CellPatchDelta (+ SheetStructureDelta shape, §5.6)
    package/               # OOXML package layer (no cell semantics here)
      zipin.py             # hostile-safe zip reader (§10)
      zipout.py            # deterministic zip writer
      xmlsafe.py           # expat wrapper: DOCTYPE/entities rejected, size/depth caps
      parts.py             # Part, Relationship, ContentTypes, PackageModel
      patch.py             # surgical byte-range patching of XML parts
    xlsx/
      reader.py            # workbook.xml, sheets, sharedStrings, styles -> model
      sheet_scan.py        # streaming sheetData scan, row byte-offset index
      writer.py            # dirty-part planner + part regeneration
      features.py          # detectors that feed the compat registry
    csvio/
      detect.py            # encoding + delimiter detection
      reader.py  writer.py # Persian digit handling, leading-zero policy
    formula/
      tokenizer.py  parser.py  ast.py
      refs.py              # A1 parsing, range math, shared-formula translation
      depgraph.py          # dependents index, dirty propagation, cycle detection
      evaluator.py         # evaluation + Excel error semantics
      functions/           # one module per category, registry-driven
    compat/
      registry.py          # feature codes, tier, handling, fixtures, test ids
      report.py            # builds CompatibilityReport from registry hits
  tests/
    unit/  roundtrip/  hostile/  persian/  formula/  oracle/
    fixtures/README.md     # provenance of every file
    fixtures/build_fixtures.py
  benchmarks/bench_100k.py
```

Boundaries inside the engine: `package/` knows nothing about cells; `model/` knows nothing about zip/XML; `xlsx/` is the only place that connects them; `formula/` depends on `model/` read access only through a small `CellReader` protocol so the evaluator can be swapped (§8).

---

## 3. Internal data model

**Handle.** `WorkbookHandle.id` is a UUID. The engine keeps a registry `id -> WorkbookState`. A handle is **not thread-safe**; `apps/api` must serialize calls per workbook (documented in the README). Memory is released by a `close` method that does not exist in the contract yet (CC-2).

**Sheet storage.** Cells are sparse in the contract but 100k × 20 = 2M cells is the working target. A dict of Python objects per cell is likely too heavy, so the default is a **column-chunked typed store** behind a `SheetStore` interface:
- per column: a tag array (empty/num/str/bool/err/formula-cached), a float64 array for number/bool/error-code, and an index array into a per-workbook string table for text;
- formulas in a side dict `(r, c) -> FormulaInfo` (text, parsed AST lazily, cached value tag);
- style id per cell in a parallel small-int array, defaulting to the row/column style when unset.
This is a hypothesis to be validated by the benchmark in §13; the interface lets me fall back to a dict store or a lazy row-window store without touching other modules.

**Values.** Numbers are stored as floats (as Excel does). Strings keep original text, never normalized (Persian `ي`/`ك` variants are user data; normalizing is a dataops operation, never silent). Dates are numbers with a date number format; `DateValue` is produced only at the edge in `get_cells` when the number format classifies as date/time (built-in ids plus custom-format token scan outside quotes and `[...]`). Excel's 1900 leap-year quirk (serial 60) and the 1904 system are handled in `dates.py` and tested. Jalali conversion is **not** in the engine (I18N_SPEC: display-side).

**Error values.** Contract `ErrValue` has 7 literals. Files can contain others (`#SPILL!`, `#CALC!`, `#GETTING_DATA`, …). Until Agent 0 decides (CC-7), they are mapped to `#VALUE!` in `get_cells` **and reported** (`xlsx.error_value.unmapped`), while the original XML stays untouched if the cell is not edited.

**Deltas (ADR-005).**
- `apply_cell_edits` returns one `CellPatchDelta` whose `before`/`after` contain **every cell whose stored content or value changed**: the edited cells and the recalculated dependents. Consequences: undo/redo is a pure patch application (`apply_delta(inverse=...)`) with no recalculation required, results are deterministic, and the API can return `delta.after` to the browser as the "changed cells" response. Cost: large fan-out produces large deltas; a cap with a typed error is planned (see risks R5). This needs Agent 0 confirmation (CC-4).
- Edit validation: exactly one of `value`/`formula`, or neither to clear (contract). Formula text is stored with the leading `=` in `Cell.f`; the XLSX `<f>` element omits it, and the reader/writer convert.
- Formula text is always **canonical en-US** (English function names, comma separators) in the model and in files; localized display is a UI concern.

---

## 4. Import pipeline (XLSX)

1. **Pre-checks** on the file (size vs `MAX_UPLOAD_BYTES`, magic bytes). OLE2 magic (`D0CF11E0`: encrypted xlsx or legacy `.xls`) is rejected with `unsupported_workbook`, reason `encrypted_or_legacy`. `.xlsb` is rejected the same way.
2. **Safe zip open** (§10) → list of entries validated before any decompression.
3. **Package model**: parse only `[Content_Types].xml` and `.rels` files; build `PackageModel` (parts, relationships, content types). Every other part is loaded lazily as raw bytes.
4. **Parse allowlist** (SECURITY_MODEL): `workbook.xml`, each referenced worksheet part, `sharedStrings.xml`, `styles.xml`. Everything else is opaque — never parsed, never executed (VBA included).
5. **Sheet scan** (streaming expat, never a full DOM): builds the cell store, the formula table, and a **row byte-offset index** (`row r -> (start, end)` in the original part bytes) used by the writer. Features found along the way (merged cells, conditional formatting, data validation, tables, legacy drawing, …) are recorded as registry hits.
6. **Report** generated from registry hits (§6).

Relationship targets are resolved inside the package namespace only; `TargetMode="External"` is never followed, only reported.

**Shared formulas** (`t="shared"`) are expanded to per-cell formulas using reference translation (`formula/refs.py`) so edits and evaluation see ordinary formulas; the original XML for unedited rows is retained for export so the expansion is not written back unless the row is regenerated. **Array formulas** (`t="array"`) are read as formulas with a `partial` status; evaluation of array-valued results is out of scope initially (cached values kept).

---

## 5. OOXML package layer: how unknown parts are preserved

### 5.1 Principle
The package is modeled as an ordered list of parts. Each part has a *state*: `clean` (original bytes retained), `dirty` (regenerated or patched), `dropped` (removed with a report item), or `added`. **Export never re-serializes a clean part**; it writes the original decompressed bytes. Byte-equality is therefore guaranteed for clean parts by construction and verified by tests (compare decompressed bytes, part by part, original vs exported).

### 5.2 What is preserved
- All parts the engine does not understand (`customXml/*`, `xl/pivotCache*`, `xl/pivotTables/*`, `xl/charts/*`, `xl/drawings/*`, `xl/media/*`, `xl/embeddings/*`, `xl/vbaProject.bin`, `xl/externalLinks/*`, `xl/theme/*`, `docProps/*`, printer settings, unknown future parts).
- Their `.rels` files, and their `[Content_Types].xml` `Default`/`Override` entries.
- Unknown XML **inside** understood parts (e.g. `extLst`, `conditionalFormatting`, `dataValidations`, `sheetPr`, `cols`, `mergeCells`, `pageSetup`, `legacyDrawing`, `tableParts`, mc:AlternateContent, unknown namespaces): these live in sheet XML, so they are handled by the patch strategy below rather than by regeneration.
- Zip entry **order** of the original is kept (`[Content_Types].xml` first if it was).

### 5.3 Dirty-part strategy (patch, don't regenerate)
A cell edit does not regenerate a worksheet from the model — that would lose every unknown child element. Instead:
- `sheetN.xml` for an **unedited sheet**: written as original bytes.
- `sheetN.xml` for an **edited sheet**: a single streaming pass over the original bytes that (a) copies every byte outside `<sheetData>` verbatim, (b) inside `<sheetData>`, copies untouched `<row>` elements verbatim using the stored byte offsets, (c) regenerates only rows that contain edited cells — preserving the row element's own attributes (`ht`, `s`, `customFormat`, `hidden`, `spans`, …) and the original bytes of unedited cells inside that row, (d) inserts brand-new rows in order, (e) updates `<dimension>` only if the used range actually changed.
- `sharedStrings.xml`: **append-only.** Existing `<si>` entries are never renumbered (so untouched rows stay valid); new strings are appended and `count`/`uniqueCount` patched. If an edit adds no new strings, the part stays clean. (Writing edited text cells as `inlineStr` is the fallback if append-only proves problematic.)
- `styles.xml`: clean in v1 (the contract has no style-edit API). If a style-edit API is added later it will be append-only too.
- `workbook.xml`: patched only for specific attributes/elements (`calcPr`, defined names if edited, sheet view flags live in the sheet part).
- `calcChain.xml`: see §5.5.

### 5.4 Cross-part invalidation warnings
Registry entries declare dependencies ("a pivot cache references a sheet range", "a table definition has `ref`", "a chart series references a range", "data validation lists", "conditional-format ranges"). On export, for every edited cell range that intersects a range referenced by a *preserved* part, the export `CompatibilityReport` includes an item (e.g. `xlsx.pivot_cache.stale_risk`, status `partial`, `preserved=true`, location = the part and range). Detecting range references inside preserved parts is limited to the parts for which I write a small, tested extractor; for others the report states that stale-risk could not be assessed (honest "unknown", not silence).

### 5.5 Deliberate deviations from byte-preservation (always reported)
- `calcChain.xml`: when formulas are added or removed, a stale chain can make Excel report corruption. Plan: **drop** the part together with its relationship and content-type override, reported as `xlsx.calc_chain.dropped` (info; Excel rebuilds it). Surgical removal of one `Relationship` and one `Override` element keeps the rest of those parts byte-equal.
- `calcPr`: when any formula cell was edited or recalculated by us, set `fullCalcOnLoad="1"` so Excel recomputes everything on open (our cached values are for Gridora's display; Excel is not asked to trust them). Reported as info.
- Zip container metadata (timestamps, compression level, extra fields) is **not** preserved; part *content* is.

### 5.6 Structure delta (shape owned by me per contract)
`SheetStructureDelta.change` will be specified in `packages/engine/docs/STRUCTURE_DELTA.md` before any structure operation is implemented. Draft vocabulary: `{"op": "set_rtl", "before": bool, "after": bool}`, later `insert_rows`, `delete_rows`, `rename_sheet`, … Not implemented in the first PRs (CC-5).

### 5.7 RTL flag
`SheetMeta.rtl` is read from `<sheetView rightToLeft="1">` of the first/active view and written by patching **only that attribute** on the sheet part (other sheet bytes untouched). Tested with a Persian fixture round-trip. Multiple `sheetView` elements: first is authoritative, others preserved; reported as `partial` if they disagree.

---

## 6. Compatibility feature registry

`compat/registry.py` holds a versioned table. Each entry:

| Field | Meaning |
|---|---|
| `code` | stable string, e.g. `xlsx.pivot_table`, `xlsx.vba_project`, `xlsx.conditional_format.icon_set`, `xlsx.external_link`, `xlsx.merged_cells`, `xlsx.table`, `xlsx.data_validation`, `xlsx.shared_formula`, `xlsx.array_formula`, `xlsx.dynamic_array`, `xlsx.rtl_view`, `csv.encoding_guessed`, `formula.unsupported_function` |
| `tier` | `supported` / `partial` / `preserved` / `unsupported` (COMPATIBILITY_STRATEGY) |
| `detect` | function (part name / XML event) that produces hits and locations |
| `handling` | what we do: read / edit / preserve bytes / drop+warn |
| `fixtures` | fixture files exercising it |
| `tests` | test ids that prove the tier |

**Mapping to the contract.** `CompatItem.status` has three values; the strategy has four tiers. Mapping: `supported → supported`; `partial → partial`; `preserved → status "unsupported", preserved=true, editable=false`; `unsupported → status "unsupported", preserved=false`. `message` states the tier in plain words so the UI does not have to infer it.

**Honesty gate (CI):** a registry entry may declare tier `supported` or `partial` only if it lists at least one fixture and one passing test id; a test checks this. The README's compatibility statements are generated from the registry.

**Report size.** Reports aggregate by code with a count and a bounded list of sample locations (default 50), and say explicitly when the list is truncated — so a 100k-row file with 100k conditional formats does not produce a 100k-item report, and truncation is never silent.

---

## 7. CSV

- **Encoding detection** (`import_csv`, `options.encoding=None`): BOM → `utf-8-sig` (or UTF-16 BOM). Else strict UTF-8 decode (valid multi-byte UTF-8 is very unlikely by chance in other encodings). Else Windows-1256 if the decoded text has a meaningful share of Arabic-script letters. Else fall back to Windows-1252 and report `csv.encoding_guessed`. Any non-explicit guess is reported with the chosen encoding. Explicit `options.encoding` always wins.
- **Delimiter**: `,` `;` `\t` `|` chosen by consistency across the first N rows (Persian-locale Excel commonly exports `;`); explicit option wins.
- **Quoting/newlines**: RFC 4180 style, quoted newlines, `""` escapes, mixed `\r\n`/`\n`.
- **Persian digits**: a field consisting entirely of digits (Latin, Persian `۰-۹`, Arabic-Indic `٠-٩`) with optional Persian separators (`٫` decimal, `٬` thousands) is normalized to Latin digits **before number parsing** (I18N_SPEC). Text fields that merely contain Persian digits among words are left unchanged. The number of normalized fields is reported (`csv.persian_digits_normalized`, info).
- **Leading zeros / identifiers**: fields such as `0912…` (phone), national IDs, postal codes with leading zeros stay **text**; numbers are inferred only when `str(float)` round-trips the original token (no loss of leading zeros, no >15-digit precision loss). Type inference is conservative; an `infer_types` option (default on, off = all text) is proposed.
- **Output**: `export_csv` writes UTF-8 **with BOM** by default (Excel opens Persian text correctly with it); Windows-1256 optional, and unmappable characters raise a typed error rather than being replaced silently. Spreadsheet-formula injection (`=`, `+`, `-`, `@` leading cells) is *not* neutralized by default (fidelity); an opt-in flag is planned and the decision is raised in §19.
- `import_csv` returns no report per contract; the report is attached as `Workbook.compat` (CC-6, clarification only).

---

## 8. Formula strategy

**Principle.** Formula evaluation sits behind an internal interface (`FormulaBackend`: parse, dependents, evaluate) so the spike (ADR-003) can swap a Rust core in later without touching `model/` or `xlsx/`. The baseline is a **pure-Python evaluator I write independently** (decision option C), because it carries no dependency and no license question.

**What is built, in order**
1. **Tokenizer/parser** for Excel formula syntax (A1 refs incl. `$`, sheet-qualified and quoted sheet names incl. Persian names, ranges, whole column/row refs, operators with Excel precedence including unary minus and `%`, string/number/bool/error literals, function calls, array constants parsed but flagged). Parse failure → cell keeps its text and cached value, reported `formula.parse_error`; never raises out of import.
2. **Dependency graph**: dependents index by cell and by range (range nodes, not per-cell fan-out, to keep 100k-row ranges cheap); dirty propagation; topological recalculation; cycle detection (`formula.circular`: cells keep cached values and are reported — Excel's iterative-calc behavior is not emulated).
3. **Evaluator** with Excel error propagation, empty-cell/text/number coercion rules, comparison semantics (case-insensitive text), 15-significant-digit behavior where Excel observably applies it, and the date system flag.
4. **Function subset** in tiers, each function added only together with tests:
   - Tier 1: `SUM AVERAGE MIN MAX COUNT COUNTA COUNTBLANK ABS ROUND ROUNDUP ROUNDDOWN INT MOD IF IFS IFERROR AND OR NOT LEN LEFT RIGHT MID TRIM UPPER LOWER CONCAT CONCATENATE VALUE ISNUMBER ISTEXT ISBLANK ISERROR`
   - Tier 2: `SUMIF SUMIFS COUNTIF COUNTIFS AVERAGEIF VLOOKUP HLOOKUP INDEX MATCH XLOOKUP DATE YEAR MONTH DAY TODAY NOW SUBSTITUTE FIND SEARCH TEXT (limited formats)`
   - Tier 3 (only if time): statistics, `SUMPRODUCT`, `ROW COLUMN`, `RAND/RANDBETWEEN` (seedable), financial basics.
   Anything else is **unsupported**: formula text kept verbatim, cached value kept, and the cell is reported `formula.unsupported_function` (aggregated by function name with counts and sample locations).
5. **Stale-dependency honesty:** a cell whose precedents include a cell with an unsupported function cannot be recomputed correctly after upstream edits; it keeps its cached value and is reported `formula.stale_dependency`.
6. **On import there is no automatic recalculation.** Cached `<v>` values are trusted for display; `recalculate()` recomputes what we can. (Recalculating on load would silently change values for unsupported dependency chains.)
7. **Security:** no network/file/shell-capable functions are implemented (`WEBSERVICE`, `HYPERLINK` evaluation, `CALL`, `REGISTER.ID`, DDE, external references); they fall into "unsupported"; external workbook links are never followed.
8. **Coverage table** `FORMULA_COVERAGE.md` is **generated from test results**, never hand-edited.

**Oracle.** LibreOffice headless is available in my environment (`soffice`) and is used as a *secondary* oracle to compare computed values on the formula fixtures. Its results are labeled "LibreOffice-observed", not "Excel-correct". Where it differs from documented Excel behavior, the test records the Excel-documented expectation and marks the oracle diff.

**Spike interaction.** If the spike (§14) shows a Rust core is clearly better for evaluation (not for XLSX I/O, which stays ours), `FormulaBackend` gets a second implementation behind PyO3 or a subprocess; the pure-Python evaluator remains as the reference in tests.

---

## 9. Persian / RTL specifics (engine side)

- Sheet names: Persian and mixed-direction names preserved verbatim; validated against Excel rules (≤31 chars, no `: \ / ? * [ ]`, not empty, case-insensitive uniqueness, no leading/trailing apostrophe); quoted correctly inside formulas (`'برگه ۱'!A1`).
- `SheetMeta.rtl` read/written as in §5.7.
- CSV: §7. Digits: stored canonical Latin; input digits normalized only in CSV numeric-field parsing and in `CellEdit` value strings that the engine is asked to parse (a `CellEdit` already carries typed values, so the engine does not guess types from text in `apply_cell_edits`).
- Persian-aware sorting/search and text normalization are dataops responsibilities (not engine).
- Fixtures: Persian sheet names, Persian text with ZWNJ, Persian/Arabic-Indic digits, `ي`/`ك` variants, RTL sheet view, Windows-1256 CSV, UTF-8 CSV with and without BOM, mixed-direction strings.
- Jalali dates: engine stores serial numbers only; non-round-trippable Jalali display formats (if any are found in files) are reported.

---

## 10. Security and resource limits

All limits live in `ResourceLimits` (injectable, with safe defaults). **Defaults below are proposals to be tuned against the 100k × 20 benchmark file and agreed with Agent 0.**

| Threat | Control |
|---|---|
| Zip bomb (size) | cap on total uncompressed size, per-entry uncompressed size, compression ratio; **budgeted streaming decompression** — header-declared sizes are not trusted, bytes actually produced are counted and the read aborted |
| Zip bomb (structure) | entry-count cap; detect **overlapping local-header ranges** / entries sharing data (non-recursive "quine"/overlap bombs); reject unsupported compression methods and encrypted entries |
| Path traversal | reject entry names with `..` segments, absolute paths, drive letters, backslashes, NUL, empty segments, duplicate names, and names equal under case-folding; names are only ever used as dictionary keys inside the engine, **never as filesystem paths** (nothing is extracted to disk) |
| XXE / DTD / entity expansion | expat parser wrapper that rejects any `DOCTYPE`/entity declaration via its declaration handlers and never resolves external entities or network resources; only UTF-8 is accepted for parsed parts (UTF-16 parts that need parsing are rejected as unsupported — opaque parts are not parsed so unaffected); depth, attribute-count and token-size caps |
| Absurd sheet dimensions | validate `<dimension>` and every cell/row ref against Excel's limits (1,048,576 rows × 16,384 cols); total non-empty cell cap (proposal: 10 M); string length cap 32,767; shared-string count cap; per-sheet row/col span cap on materialization |
| Corrupted parts | any malformed XML or missing required part → `import_failed`; no partial workbook returned |
| Time | cooperative deadline checks every N XML events / formulas evaluated (pure Python cannot be pre-empted) |
| Memory | engine tracks an estimate against a cap and aborts with a typed error; **hard enforcement is an OS-level limit in the isolated worker process (Phase 3, `apps/api`)** — I will state this plainly in the README; the engine alone does not guarantee memory safety |
| Macros / embedded objects | preserved as opaque bytes, never parsed or executed |
| Formula safety | §8 item 7 |
| Info leaks | §11 |

Hostile fixtures to build (generated by script, committed as tiny files, never downloaded): zip bomb (high ratio), overlapping-entries zip, path-traversal names (`../`, absolute, backslash, NUL), XXE with external entity, billion-laughs, DOCTYPE with parameter entities, `<dimension ref="A1:XFD1048576">` plus a cell at `XFE1`, 10M-row declared sheet, truncated zip, bad CRC, missing `[Content_Types].xml`, corrupted `sharedStrings.xml`, encrypted OLE2 wrapper, 33k-char string cell.

---

## 11. Errors

- `GridoraEngineError(code, reason, public_message)`; subclasses per family. `code ∈ ERROR_CODES` from `contracts/` (`import_failed`, `unsupported_workbook`, `file_too_large`, `unsupported_media_type`, `bad_request`, `validation_failed`, `internal_error`).
- `reason` is an engine-level stable sub-code (e.g. `zip.ratio_exceeded`, `zip.path_traversal`, `xml.doctype_forbidden`, `sheet.dimension_exceeded`, `csv.encoding_unsupported`), surfaced to the API for `ErrorDetail` (CC-8: confirm whether `reason` can ride in `ErrorDetail.code`).
- `public_message` is built from fixed templates and may include **package-internal part names** (e.g. `xl/worksheets/sheet3.xml`) and counts, but **never** filesystem paths, the input file's name, usernames, or raw exception text. Underlying `OSError`/parser exceptions are caught at the boundary and re-raised without their message (`raise … from None`); a test greps every raised message for the temp directory path and the file name.
- No stack traces cross the module boundary as data.

---

## 12. Test plan

Tooling: `pytest`, `ruff`, `mypy --strict` for `src/`. Dev-only dependency proposed: `hypothesis` (property tests for the formula parser/printer and reference translation). Python ≥ 3.11 to match `contracts/`.

| Layer | What | Notes |
|---|---|---|
| Unit | values/dates (incl. 1900 leap bug, 1904), number-format classification, ref parsing, string table, store, delta build/apply, CSV detection/parsing | |
| Package | read → write with no edits → **all parts byte-equal** (decompressed) on every fixture; entry order preserved; add/drop part cases (calcChain) change only the intended bytes | the core acceptance test |
| Round-trip | import → edit → export → re-import: compare cells, formulas, styles for supported features; unknown parts byte-equal; unedited sheets byte-equal; edited sheets: only edited rows differ outside `<sheetData>` byte-equal | |
| Delta | for random edit sequences: `apply → inverse` restores the exact prior state; redo equals the original result; dependents included | property-based |
| Compat | each registry entry with a fixture produces the expected code/tier; honesty gate (§6); report truncation is flagged | |
| Hostile | the §10 set; assert typed error, `reason`, bounded time/memory, no path leak | |
| Persian | §9 fixtures through XLSX and CSV round-trips | |
| Formula | per-function tests (Excel-documented expectations), error propagation, circular/unsupported/stale cases, determinism; LibreOffice oracle comparison where `soffice` exists (skipped otherwise, never silently counted as passed) | coverage table generated |
| Contract | `GridoraEngine` conforms to `WorkbookEngine` (`isinstance` on the runtime Protocol + signature checks); every returned object validates against `contracts` models | |
| Performance | §13, run on demand, not in CI gating | |

**Fixture corpus** (`tests/fixtures/`, with `README.md` stating origin for each file): (1) generated by `build_fixtures.py` from raw XML so provenance is exact; (2) generated through LibreOffice headless (labeled as such); (3) **real Excel-produced files** — I cannot produce these. I need the owner to supply a handful (pivot, chart, VBA, conditional formats with icon sets, Persian RTL workbook, a table with structured references) or explicitly accept that the corpus is Excel-free for now; this limitation will be stated in the README (COMPATIBILITY_STRATEGY already says LibreOffice is only a secondary oracle).

---

## 13. Benchmarks

`benchmarks/bench_100k.py` generates a deterministic 100k × 20 workbook (mixed numbers, text incl. Persian, dates, ~5% formulas, a column of cross-row formulas) and measures: **open**, **`get_cells` window** (e.g. 100×30 at top/middle/bottom, plus max 2000×200), **single-cell edit** (no dependents / many dependents), **recalculate**, **export** (clean sheets vs one dirty sheet), **peak RSS** and `tracemalloc` for the store, **delta size** for a high-fan-out edit. It records Python version, CPU, RAM, OS and commit hash; results go to `BENCHMARKS.md` only from actual runs. Targets in TESTING_STRATEGY are hypotheses; I will report numbers and let Agent 0 judge them. If open time or memory for pure Python is poor, the candidate mitigations are, in order: lazy row-window store (index pass at open, materialize on demand), columnar tuning, then the Rust-core option from the spike.

---

## 14. Engine spike (Step 1) — plan and timebox

**Timebox proposal: 3 working days, hard stop**, extendable only by Agent 0. Order is chosen so cheap disqualifications come first:
1. (0.5 d) For every candidate: read the LICENSE files **in the repo** (not the README), record the commit hash, run a dependency/license review of the lockfile, check for bundled assets with separate terms. Disqualify on unclear or incompatible license before any further work.
2. (1.5 d) Hands-on: **IronCalc** (build time, toolchain, Python binding or subprocess feasibility, XLSX round-trip on our fixtures, unknown-part preservation test with pivot/chart/VBA/custom XML, formula coverage vs LibreOffice, 100k × 20 performance, hostile inputs) and a **Python OOXML baseline (openpyxl, parse-only)**: license check, what it drops on round-trip, memory at 100k × 20.
3. (0.5 d) **GridCraft** and **Gridline**: same license/maturity audit; hands-on only if step 1 passes and time remains; Gridline is expected to be an idea source rather than a dependency.
4. (0.25 d) A pure-Python formula library candidate **only if its license is permissive** — I have not verified the licenses of the common ones and will treat any copyleft license as an immediate no.
5. (0.25 d) "Build our own" baseline: what my §8 evaluator achieves on the same formula fixtures.
6. (0.5 d) Write `SPIKE_REPORT.md` (filled matrix, recommendation among options A/B/C/D, risks, provenance list, what could be reused).

No candidate code is copied, vendored, or adapted before `SPIKE_REPORT.md` and a `THIRD_PARTY_NOTICES.md` entry exist and Agent 0 has decided (ADR-003). Spike scratch work stays outside the repo or under an untracked directory.

My working assumption going in (to be tested, not asserted): own package layer + own pure-Python XLSX I/O; the open question is only the formula core.

---

## 15. Sequence of PRs after plan approval

Aligned to `docs/INTEGRATION_PLAN.md` slices; each PR small, with tests and README/status updates.

| PR | Content | Slice |
|---|---|---|
| E0 | Package skeleton: `pyproject`, `errors`, `limits`, CI wiring for the engine, contract-conformance test with stubbed methods | — |
| E1 | CSV import/export + sheet store + `get_cells` + dates/values | 1 |
| E2 | Spike report (parallel track; independent of E1) | — |
| E3 | Hostile-safe zip + safe XML + package model + byte-equal no-op round-trip | 2 |
| E4 | XLSX read (workbook, sheets, shared strings, styles-lite) + compat registry + import `CompatibilityReport` | 2 |
| E5 | `apply_cell_edits`, deltas, undo/redo semantics (values only) | 3 |
| E6 | XLSX export with dirty-row patching, sharedStrings append, calcChain handling, RTL flag, export report | 3, 7 |
| E7 | Formula parser + depgraph + Tier 1 functions + recalculation | 3 |
| E8 | Tier 2 functions, stale/unsupported reporting, LibreOffice oracle tests | — |
| E9 | 100k benchmark + `BENCHMARKS.md`; performance fixes | — |

---

## 16. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Pure-Python parse/memory at 100k × 20 is too slow or heavy | UX / server capacity | columnar store, lazy row-window, measured early (E1/E9); Rust option via spike |
| R2 | Row-offset patching is wrong on exotic XML (namespaces, `mc:AlternateContent`, CDATA, odd whitespace) | corrupt output | fall back to "regenerate whole `<sheetData>`, copy rest verbatim"; fuzz/round-trip tests; **never** regenerate whole sheet from the model |
| R3 | Excel refuses to open our output ("repair" prompt) | trust | I cannot run Excel. Mitigate with strict schema-conscious writing, LibreOffice open test, and by asking the owner to open exported samples in real Excel and report back before any "works in Excel" claim |
| R4 | Formula semantics divergence from Excel (coercion, dates, text, floating point) | wrong numbers | small documented subset, Excel-documented expectations in tests, `fullCalcOnLoad`, stale/unsupported reporting |
| R5 | Large dependent fan-out makes deltas huge | memory, latency | delta size cap with typed error; range-node dependency graph; benchmark |
| R6 | Dropping `calcChain` or setting `fullCalcOnLoad` surprises users | minor fidelity | always reported as info; documented |
| R7 | Stale-risk detection inside preserved parts is incomplete | silent invalidation of pivots/charts/tables | explicit "could not assess" report items; extractors only for tested parts |
| R8 | No real Excel files in the corpus | false confidence | corpus README states provenance; owner asked to supply files (§12) |
| R9 | Cooperative time limits cannot stop a pathological single C-level call | DoS | OS-level limits in the API worker process (Phase 3); engine runs only on pre-validated, budgeted streams |
| R10 | Contract gaps (styles, layout, structure ops, handle lifecycle) block a usable UI | schedule | §17 raised now; I keep working against the current contract |
| R11 | `xlsm` handling (macro-enabled content type vs `.xlsx` extension) | Excel refuses to open | VBA part preserved; main content type preserved as-is; export reports the extension requirement; decision requested (§19) |

---

## 17. CONTRACT_CHANGE proposals

None of these block Step 1 or the first PRs. I keep working against the current contract until Agent 0 decides.

- **CC-1 — `file_id` for imports.** `Workbook.file_id` is required but `import_xlsx(path)` / `import_csv(path, options)` have no way to receive it. Proposal: optional keyword `file_id: str | None = None` on both. Workaround: engine fills a placeholder and `apps/api` overwrites it.
- **CC-2 — Handle lifecycle.** Add `close(wb: WorkbookHandle) -> None` (and document that handles are not thread-safe). Without it, working copies cannot be released deterministically.
- **CC-3 — Read access to formatting and layout.** The protocol exposes only `Cell.s`/`Cell.t` ids; there is no way to fetch the style table (number formats, fonts, fills, borders, alignment), column widths, row heights, hidden rows/columns, merged ranges, or frozen panes beyond `SheetMeta.frozen`. The grid UI and the "styles preserved" acceptance criterion need these. Proposal: `get_styles(wb, ids) -> list[StyleInfo]` and `get_sheet_layout(wb, sheet_id, window) -> SheetLayout` with matching models.
- **CC-4 — Delta semantics clarification.** Confirm that `CellPatchDelta.before/after` from `apply_cell_edits` include recalculated dependents (§3), so that the same delta is both the undo record and the "changed cells" response to the browser, and that `apply_delta` does not recalculate.
- **CC-5 — Structure operations.** No method exists for insert/delete rows or columns, sheet add/rename/delete/reorder/hide, or setting `rtl`. `SheetStructureDelta.change` is mine to define, but nothing creates such a delta. Proposal: `apply_structure_change(wb, change: dict) -> Delta`. Out of scope for E0–E7 unless Agent 0 wants it earlier. Reference rewriting on structure changes is the riskiest formula feature; I would schedule it after E8.
- **CC-6 — CSV report and options (clarification).** `import_csv` returns no report → I attach it to `Workbook.compat`. `CsvOptions` is a Protocol; the engine will ship a concrete `CsvImportOptions` dataclass; I propose adding `infer_types: bool` to the Protocol.
- **CC-7 — Error values.** `ErrValue` lacks `#SPILL!`, `#CALC!`, `#GETTING_DATA`, `#UNKNOWN!`. Proposal: add them (additive).
- **CC-8 — Error `reason`.** Confirm that an engine-level stable `reason` can be surfaced via `ErrorDetail.code` while the top-level code stays in `ERROR_CODES`.

---

## 18. Dependencies and copied code

- **Runtime:** none beyond the Python standard library (`zipfile`, `xml.parsers.expat`, `csv`, `array`, `struct`, `decimal`) and `pydantic>=2.6,<3` (already required by `contracts/`).
- **Dev:** `pytest`, `ruff`, `mypy`, `hypothesis` (property tests). All to be recorded by Agent 0; licenses to be listed in the PR that adds them.
- **Optional test tool:** LibreOffice (system package, oracle only, not a dependency of the product).
- **Copied code:** none. Nothing will be copied, adapted or ported from IronCalc, GridCraft, Gridline, openpyxl or any other project before a license check, `THIRD_PARTY_NOTICES.md` entry and Agent 0's decision (§14). Ideas studied from others are recorded as "idea only".

---

## 19. Open questions for Agent 0

1. Approve the proposed spike timebox (3 working days, hard stop) and the candidate order, or set another.
2. Accept the "own pure-Python package layer + own baseline evaluator, Rust core only if the spike justifies it" working assumption for E0–E7.
3. Can the owner supply real Excel-produced fixtures (§12), and open exported files in Excel to confirm no repair prompt?
4. Defaults for resource limits (§10), especially the 10 M cell cap and total uncompressed cap, against the realistic file sizes the owner expects (upload cap is 100 MB).
5. CSV export: leave formula-injection neutralization opt-in (my proposal) or default-on?
6. `.xlsm` input: accept-and-preserve VBA (my proposal, with an extension warning) or reject in v1?
7. Decisions on CC-1 … CC-8.

---

## 20. Honesty statement

As of this PR: no engine code exists, no feature is supported, no test proves anything about XLSX handling, and `docs/INTEGRATION_PLAN.md` still lists `packages/engine` as **Planned**, which is accurate. Every limitation above (no Excel in my environment, cooperative-only time limits, formula subset, reduced fidelity for dynamic arrays and error values) will be repeated in the module README as the implementation lands.
