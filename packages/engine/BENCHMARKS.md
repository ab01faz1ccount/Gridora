# Engine benchmarks

Only numbers from actual runs are recorded here. Re-run: `python benchmarks/bench_csv_100k.py`.
Targets in docs/TESTING_STRATEGY.md are hypotheses; this file only reports what was measured.

## E1 — CSV import / window read / export, 100,000 rows x 20 columns

Environment: Python 3.12.3, Linux container, **1 CPU**, glibc 2.39, commit of branch
`feature branches`. Deterministic generated file (seed 1234): numbers, decimals, Persian text,
leading-zero identifiers, Persian-digit numbers, ~3% empty cells; 19.4 MB.

| Operation | Result |
|---|---|
| `import_csv` (detect + parse + store) | 4.35 s |
| RSS growth after import | 81 MB |
| Cells stored / string-table entries | 1,939,673 / 393,933 |
| Typed-array store (allocated chunks) | 18.0 MB |
| `get_cells` 100x20 (top / middle / bottom) | 12 / 10 / 11 ms |
| `get_cells` 1000x100 (contract max window) | 142 ms |
| `export_csv` | 1.00 s (17.6 MB) |
| tracemalloc current / peak during import (separate, slower pass) | 71.5 / 170.9 MB |

Reading it honestly:
- This answers Phase 2 review C1.1 for the **CSV** path only. XLSX import (shared strings, styles,
  formula parsing, row-offset indexing) does not exist yet; its cost will be measured at E4 and may
  differ substantially. Nothing here says that XLSX open meets any target.
- The peak is dominated by Python objects (the decoded text and unique strings), not by the
  column-chunked store (18 MB). The store design is not the bottleneck at this size.
- Single-cell edit, recalculation and delta size are not measured: those features do not exist yet.
- The container has one CPU and shared hardware; treat absolute times as indicative only.

## Probe — cost of parsing a 100k x 20 worksheet (NOT the XLSX reader)

`benchmarks/probe_xlsx_sheet_parse.py` measures a lower bound for XLSX open before the reader
exists (Phase 2 review C1.1). Same environment as above. Synthetic sheet XML in Excel's usual
shape, 77.6 MB uncompressed, 1,939,473 cells.

| Operation | Result |
|---|---|
| expat with no handlers (floor) | 0.98 s |
| expat stream parse of `<sheetData>` into the real `SheetStore` | 5.75 s |
| tracemalloc peak of that parse | 25.4 MB (strings not included: shared strings are not parsed) |
| Row byte-offset index via `bytes.find(b"<row ")` | 0.10 s (100,000 rows) |
| Parse a 100-row window on demand from the original bytes | 3.7 ms |

What this means, and what it does not:
- Eager full parse is a **lower bound of ~6 s** for the worksheet alone on this 1-CPU container.
  The real reader also parses shared strings (~390k entries here), styles, formulas and features,
  so eager open will be slower. If "open" must mean "everything materialized", pure Python is
  likely to miss a "few seconds" target.
- A lazy design looks viable: index rows cheaply, parse only the requested window. The byte-scan
  index is a *hint*: it must be validated when a row is parsed and fall back to a full safe parse
  on mismatch (a crafted file can contain `<row ` inside a comment or CDATA section).
- Not measured: shared-string parsing, formulas, `<dimension>`/used-range correctness, memory of
  the string table, real Excel-produced files (the XML here is synthetic).

## E3 — package open and no-op round trip, 100k x 20 XLSX

Command: `python benchmarks/bench_package_roundtrip.py` (generates a deterministic 15.9 MB file with
`benchmarks/xlsx_fixture.py`; raw-XML fixture, not Excel-produced). Same 1-CPU container, Python 3.12.3.

| Operation | Result |
|---|---|
| `PackageModel.open` (zip validation + content types + relationships) | 0.001 s warm cache; one earlier run with a cold file cache measured 0.34 s |
| No-op write (stream every part from the source archive to the output) | 2.19 s |
| Max RSS of the whole process | 45 MB (parts are streamed, never held whole) |
| All parts byte-equal after the round trip | yes (decompressed content compared per part) |

Reading it honestly: this is container work only. No sheet XML is parsed yet (that is E4), the
file has no unknown parts (those are covered by the unit tests, not by this benchmark), and the output
zip is recompressed with Python's deflate (container metadata is not preserved; part content is).

## E4 — XLSX open (lazy reader), 100k rows x 20 columns

Command: `python benchmarks/bench_xlsx_open_100k.py`. Same 1-CPU container, Python 3.12.3. Fixture:
`benchmarks/xlsx_fixture.py` (raw XML, **not Excel-produced**): 15.9 MB zip, 73.8 MB sheet XML, 100k rows,
~1.94 M cells, 50k unique shared strings, 100k formula cells (column T, with cached values).

| Operation | Result |
|---|---|
| `import_xlsx` (zip validation, workbook/styles/shared strings, sheet spool + row index, report) | 0.85 s warm (1.64 s on the first, cold-cache run); RSS +77 MB (includes the mmap-ed 74 MB spool pages, which the OS can evict) |
| First read of a 100x20 window, cold block (top / middle / bottom) | 38 / 35 / 26 ms |
| Contract-max window 1000x100 | 0.26 s |
| Re-read of an already parsed window | 10 ms |
| Parse of every row, block by block (no Cell objects) | 11.1 s; resulting store 22 MB, 1,942,813 cells |
| Same through `get_cells` windows (builds contract `Cell` objects) | 26.7 s, RSS +152 MB |
| Eager full parse (`materialize_all`, also the fallback path) | 12.7 s, RSS +98 MB |

Reading it honestly:
- **Opening is fast because it is lazy**, not because parsing is fast. Pure-Python parsing runs at about
  150k cells/s (~6.5 us per cell, dominated by expat callbacks). Anything that needs the whole sheet
  (recalculation at E7, table conversion for dataops) pays ~11-13 s per 100k x 20 sheet; building
  contract `Cell` objects costs about as much again, so whole-sheet reads must not go through `get_cells`
  (a bulk read path will be needed; raised in the PR).
- The row index and the used-range hints come from a byte scan (0.1 s for 100k rows); `spans` /
  `<dimension>` give the width. Hints can be wrong in crafted files: parsed rows are cross-checked and a
  mismatch falls back to the full safe parse (tests cover a decoy `<row` in a comment).
- Memory: the sheet XML is spooled to a private temp file (not held in RAM); the parsed store costs
  ~11 bytes per slot plus interned strings. Disk use equals the decompressed sheet size (bounded by
  `max_part_bytes`).
- Not measured: Excel-produced files, many sheets, wide sheets, rich text, shared-formula-heavy files,
  inline-string-heavy files, repeated opens (spool cleanup is tested, not benchmarked).
- A micro-optimization pass (cached reference parsing and name lookup) did not change the parse time
  measurably; a fast path that bypasses expat would change the safety model and is not attempted.
- For comparison, the spike measured IronCalc (Rust) loading the same shape of file in ~1.1 s including
  formula parsing; that is the only route found so far to fast whole-sheet access.

## E5 — edit and undo latency, 100k x 20 XLSX (lazy reader)

Command: `python benchmarks/bench_edits_100k.py`. Same file and container as E4. Single runs.

| Operation | Result |
|---|---|
| 1 edit in a cold 256-row block (the block is parsed first) | 22 ms |
| 1 edit in a warm block | 0.1 ms |
| Undo of that edit (`apply_delta`, inverse) | < 0.1 ms |
| 10,000-cell edit (500 rows x 20 cols, cold blocks) | 266 ms |
| Undo / redo of the 10,000-cell edit | 77 ms / 27 ms |
| Delta of 10,000 cells -> JSON | 19 ms, 1.6 MB (before + after) |

Reading it honestly:
- There are no formulas to recalculate yet (E7), so "edit" is value-only and deltas contain exactly the
  edited cells. Dependents of an edited cell are **not** updated (their cached values go stale);
  the export report (E6) will say so and set `fullCalcOnLoad`.
- A delta costs ~160 bytes per cell in JSON; at the 200,000-cell cap that is ~32 MB per history entry,
  which is the maintainer's/the platform module's call to budget (cap is `max_patch_cells`, default 200,000).
- Sheets that contain shared or array formulas are loaded completely on the first edit (so the
  protection check sees every formula group): ~11-13 s for a 100k x 20 sheet of this kind. The
  benchmark file has none.

## Corpus — open times of real and hostile files (`corpus/`, Review 4 order)

Command: `python benchmarks/corpus_report.py`. 1-CPU container, Python 3.12.3, **single run per file**, warm
disk cache. "import" = `import_xlsx` (validation, workbook/styles/strings, sheet spool + index, report);
"parse-all" = time to materialize every row afterwards; "RSS" = process memory growth after import and after parsing (includes the OS page cache of the spooled sheet, which can be evicted; tiny files read as 0); "report" = items by status in the import report; "cells" = cells with a value or formula, equal to an
independent ElementTree count in the tests. `-` in cells/s: too fast to time.

| file | size KB | import s | parse-all s | cells | cells/s | RSS after import / parsed MB | report (supported/partial/preserved+unsupported) | note |
|---|---:|---:|---:|---:|---:|---:|---|---|
| StructuredRefs-lots-with-lookups.xlsx | 318 | 0.033 | 0.168 | 37,696 | 224,862 | 3 / 7 | 0/3/8 |  |
| 57181.xlsm | 327 | 0.014 | 0.136 | 12,454 | 91,809 | 2 / 6 | 0/3/8 |  |
| 47813.xlsx | 54 | 0.004 | 0.011 | 2,164 | - | 0 / 0 | 1/2/4 |  |
| dataValidationTableRange.xlsx | 114 | 0.021 | 0.033 | 6,615 | - | 0 / 0 | 0/2/7 |  |
| ExcelPivotTableSample.xlsx | 19 | 0.002 | 0.001 | 50 | - | 0 / 0 | 0/0/3 |  |
| DataTableCities.xlsx | 23 | 0.002 | 0.001 | 185 | - | 0 / 0 | 0/1/4 |  |
| WithChartSheet.xlsx | 30 | 0.002 | 0.002 | 267 | - | 0 / 0 | 0/0/5 |  |
| 54436.xlsx | 12 | 0.001 | 0.000 | 28 | - | 0 / 0 | 0/1/1 |  |
| LIBRE_OFFICE-116306-0.xlsx | 2,793 | 0.127 | 2.467 | 662,923 | 268,693 | 17 / 23 | 1/0/2 | manifest `names` = auto-filter name only (filter reported) |
| 61495-test.xlsm | 20 | 0.003 | 0.001 | 4 | - | 0 / 0 | 0/1/2 |  |
| testNames.xlsm | 13 | 0.001 | 0.000 | 15 | - | 0 / 0 | 0/2/1 |  |
| ExcelWithAttachments.xlsm | 61 | 0.002 | 0.001 | 6 | - | 0 / 0 | 0/1/6 |  |
| 60512.xlsm | 65 | 0.003 | 0.004 | 564 | - | 0 / 0 | 0/2/5 |  |
| ConditionalFormattingSamples.xlsx | 639 | 0.012 | 0.015 | 1,723 | - | 0 / 1 | 0/3/7 |  |
| NewStyleConditionalFormattings.xlsx | 13 | 0.001 | 0.002 | 340 | - | 0 / 0 | 0/2/2 |  |
| conditional_formatting_with_formula_on_second_sheet.xlsx | 68 | 0.002 | 0.000 | 2 | - | 0 / 0 | 0/1/2 |  |
| DataValidationEvaluations.xlsx | 13 | 0.001 | 0.001 | 139 | - | 0 / 0 | 0/2/3 | manifest `drawings` = legacy comment shapes (reported as comments) |
| FormulaEvalTestData_Copy.xlsx | 63 | 0.007 | 0.021 | 4,177 | - | 0 / 0 | 0/2/3 | manifest `drawings` = legacy comment shapes (reported as comments) |
| 45544.xlsx | 42 | 0.004 | 0.004 | 589 | - | 0 / 0 | 0/3/3 |  |
| MatrixFormulaEvalTestData.xlsx | 15 | 0.001 | 0.003 | 697 | - | 0 / 0 | 0/2/1 |  |
| xlookup.xlsx | 12 | 0.001 | 0.001 | 97 | - | 0 / 0 | 0/3/0 |  |
| 51710.xlsx | 83 | 0.008 | 0.064 | 13,688 | 215,534 | 1 / 1 | 0/2/0 |  |
| Tables.xlsx | 53 | 0.006 | 0.013 | 2,111 | - | 0 / 0 | 0/4/1 |  |
| VLookupFullColumn.xlsx | 13 | 0.002 | 0.004 | 623 | - | 0 / 0 | 0/2/0 |  |
| 46535.xlsx | 306 | 0.018 | 0.034 | 7,156 | - | 0 / 0 | 0/2/3 |  |
| NumberFormatTests.xlsx | 21 | 0.003 | 0.007 | 1,314 | - | 0 / 0 | 1/2/1 |  |
| GeneralFormatTests.xlsx | 35 | 0.002 | 0.003 | 296 | - | 0 / 0 | 1/2/1 |  |
| right-to-left.xlsx | 14 | 0.001 | 0.000 | 8 | - | 0 / 0 | 0/0/2 | manifest `drawings` = legacy comment shapes (reported as comments) |
| bug62181.xlsx | 854 | 0.074 | 0.669 | 175,095 | 261,777 | 7 / 11 | 0/0/0 | manifest `media` = empty directory |
| Product-Sales-Region.xlsx | 146 | 0.012 | 0.107 | 28,149 | 263,960 | 1 / 1 | 0/1/0 |  |
| file_example_XLSX_5000.xlsx | 184 | 0.027 | 0.165 | 40,007 | 242,061 | 2 / 2 | 0/0/1 |  |
| file_example_XLS_5000.xls | 656 | - | - | - | - | - | - | rejected: `xlsx.legacy_xls` |
| open_data_us.csv | 8 | 0.001 | 0.000 | 396 | - | 0 / 0 | 0/1/0 |  |
| softwiro-piece-rate-payroll-2026-11-16.xlsx | 131 | 0.011 | 0.054 | 7,034 | 129,115 | 1 / 1 | 2/2/5 |  |

Hostile files:

| file | outcome |
|---|---|
| 58616.xlsx | `unsupported_workbook` / `xlsx.encrypted` (0.000 s) |
| clusterfuzz-testcase-minimized-POIFuzzer-5040805309710336.xl | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-482872700108800 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-508944730560921 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-518504958957977 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-593738531956326 | `import_failed` / `zip.bad_crc` (0.005 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-612346160781721 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-641936625591910 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-POIXSSFFuzzer-644825896334131 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-XLSX2CSVFuzzer-50254011169505 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-XLSX2CSVFuzzer-55428654792704 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-XLSX2CSVFuzzer-56364391516078 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-XLSX2CSVFuzzer-65042258967920 | `import_failed` / `zip.corrupt` (0.000 s) |
| clusterfuzz-testcase-minimized-XLSX2CSVFuzzer-65945574140805 | `import_failed` / `zip.corrupt` (0.000 s) |
| crash-274d6342e4842d61be0fb48eaadad6208ae767ae.xlsx | `import_failed` / `zip.corrupt` (0.000 s) |
| crash-9bf3cd4bd6f50a8a9339d363c2c7af14b536865c.xlsx | `unsupported_workbook` / `xlsx.encrypted` (0.000 s) |
| deep-data.xlsx | `import_failed` / `zip.corrupt` (0.000 s) |
| protected_passtika.xlsx | `unsupported_workbook` / `xlsx.encrypted` (0.000 s) |

Reading it honestly:
- **Parse rate on real files: ~150k-255k cells/s** (the largest, `LIBRE_OFFICE-116306-0.xlsx`, 662,923 cells,
  parses in 2.6 s; `bug62181.xlsx`, 175,095 cells, in 0.69 s). Extrapolating linearly to a 100k x 20 sheet
  (~2 M cells) gives roughly 8-13 s. That is an extrapolation: **no real Excel-made 100k x 20 file exists in the
  corpus**, and the largest file was not necessarily made by Excel. Gate in ADR-015: 30 s.
- Import (lazy) stays under 0.15 s for every file here, including the 663k-cell one.
- **Nothing important is lost in the reports of the 29 Apache POI files.** The manifest's feature flags and our
  reports differ in 5 files, all verified by tests as non-losses: three list `drawings` that are only legacy
  comment shapes (`vmlDrawing`, reported as `xlsx.comments`); one lists `media` but `xl/media/` is an empty
  directory; one lists a defined name that is only the auto-filter bookkeeping name `_xlnm._FilterDatabase`
  (the filter is reported as `xlsx.auto_filter`). Sheet counts, formula counts, error-cell counts and date1904
  match the manifest in all 29; cell counts match an independent oracle in all 29 + 2 private plain files + softwiro.
- **The hostile corpus tests less than its size suggests:** 15 of the 18 files are truncated or damaged ZIP
  containers without a central directory (Python's `zipfile` and `unzip` reject them too; Java streaming
  readers tolerate them). They prove typed rejection of broken containers, not the XML or limits paths. We do
  **not** try to recover them by streaming local headers: that would bypass the central-directory checks
  (overlap, declared sizes, entry count). Three files are encrypted OLE2 packages (`xlsx.encrypted`).
- `file_example_XLS_5000.xls` (old BIFF): rejected at once with `unsupported_workbook` / `xlsx.legacy_xls`.
- Files tested through the Persian lens: `softwiro-piece-rate-payroll` (all 7 sheets RTL, 6,806 ordinary
  formulas, 5 protected sheets, DV/CF/merges/hyperlinks, `fullCalcOnLoad`) is the only Excel-made RTL workbook;
  `right-to-left.xlsx` (POI) has Arabic text but no RTL sheet view. No Persian (as opposed to Arabic) workbook
  with a Jalali date format is in the corpus.
- Not covered: `private/actual_budget_workbook_br.xlsx` (listed in the manifest, not in the repository).

## E6 — export, 100k x 20 XLSX (row patching)

Command: `python benchmarks/bench_export_100k.py`. Same file and container as E4/E5, single runs.

| Operation | Result |
|---|---|
| `export_xlsx`, no edits (verbatim copy of every part) | 2.26 s |
| after 1 edit (one row rebuilt, rest copied from the spooled original) | 1.95 s |
| after +10,000 edited cells (500 rows rebuilt) | 2.08 s |
| Re-import of the exported file (lazy) | 0.85 s |
| Max RSS of the whole process (import + edits + 3 exports + re-import) | 219 MB |

Reading it honestly: the time is dominated by re-compressing the 74 MB sheet with deflate, not by row
rebuilding (rebuilding 500 rows costs less than the noise between runs). Memory stays flat because the
sheet is streamed from the spool, never held whole.

### Export round trip on the real corpus (`tests/corpus/test_corpus_export.py`)
All 31 readable corpus files (29 Apache POI + 2 private xlsx + softwiro) go through import, three
deterministic value edits per sheet, export, and a re-import by a fresh engine: **the fingerprint of every
cell of every sheet is identical** to the live workbook, only the expected parts change (edited sheets,
`workbook.xml` gaining `fullCalcOnLoad`, and `workbook.xml.rels`/`[Content_Types].xml`/`calcChain.xml` when
formulas changed), and inside an edited sheet only the rows that contain edits differ, byte for byte.
LibreOffice (secondary oracle, not Excel) opens the exported file and shows the edit for 5 representative files
(calcChain dropped, xlsm with VBA, pivot, tables, a 663k-cell sheet).
**A bug this found:** Excel-made rows carry prefixed attributes (`x14ac:dyDescent`); the lazy reader parsed row
slices with namespace processing, the prefix was unbound in the slice, and every such sheet silently fell back to
the slow full parse (my synthetic fixtures never had prefixes, so the 100k benchmark did not show it). Row
slices are now parsed without namespace processing. Before the fix 14 of the 31 files could not be exported
(`export.sheet_not_patchable` / `xml.malformed`); after it, none.

## Re-measurement after the namespace fix (E5b-1 branch)

The E4 benchmark was run again after row slices stopped being parsed with namespace processing (see the E6 section).
Same container class, single runs, **but the host differs between runs (kernel string in the header), and
run-to-run spread on this machine is about +-30%**, so read the change as "faster", not as a precise factor:
`import_xlsx` 0.67 s (was 0.85 s); eager full parse 8.5 s (was 12.7 s); every row through `get_cells` windows
18.9 s (was 26.7 s); window reads unchanged (35-46 ms cold, 0.26 s for 1000x100). The older tables above are kept
as measured; the ADR-015 gate (30 s) is met by either set.

## E5b-1 — columnar read/write (ColumnarEngine, contract 0.4.1), 100k x 20 XLSX

Command: `python benchmarks/bench_columnar_100k.py`. Single run.

| Operation | Result |
|---|---|
| `read_range_columnar`, whole sheet, cold (includes parsing the sheet) | 6.84 s |
| same, sheet already parsed | 0.21 s = **0.11 us per non-empty cell** (1,942,813 cells; kinds `num`, `str`) |
| `get_cells` over the same cells, already parsed | 17.5 s = 9.0 us per cell: columnar is **~82x faster** on parsed data |
| `write_range_columnar` of identical data (nothing changes) | 3.9 s (compares 2 M cells, ~2 us each; delta empty) |
| `write_range_columnar` changing one column (100,000 cells) | 3.5 s; max RSS of the whole script 978 MB (keeps three copies of the data as Python lists plus the cell objects of the comparison) |

Reading it honestly: the cost of a first whole-sheet operation is the parse (6.8 s here), not the conversion.
The write path is per-cell Python (~2 us/cell) and is capped at 200,000 changed cells until E5b-2; a bulk path for
large writes belongs to the snapshot work. Real files: `tests/corpus/test_corpus_columnar.py` compares the columnar
read with `get_cells`, cell by cell, on every sheet (first 5000 rows) of every readable corpus file.

## E5b-2 — range snapshot deltas (blob codec + bulk apply), 100k x 20 XLSX

Command: `python benchmarks/bench_snapshot_100k.py` (in-memory fake `BlobStore`). Single run, 1 CPU. The range is
19 columns x 100,000 rows (1.8 M cells); the numeric columns are changed (+1), 775,960 cells actually differ.

| Operation | Result |
|---|---|
| `read_range_columnar` (includes parsing the sheet) | 9.94 s |
| `write_range_columnar` -> `range_snapshot` (build arrays, encode before + after, store, apply) | 4.92 s |
| Blob size (before / after), zlib level 6 | 9.1 MB / 9.1 MB for 1.8 M cells (raw columns: 19.8 MB) |
| The delta itself (what the history table stores) | 251 bytes of JSON |
| Undo / redo (`apply_delta`, bulk array writes) | 0.65 s / 0.56 s |
| `export_xlsx` after the bulk write (all 100,000 rows rebuilt) | 22.5 s; max RSS 349 MB for the whole script |

Reading it honestly:
- The cap on history entries is lifted only because the blob store absorbs the size: 9.1 MB per side here;
  random numbers compress poorly (3-8 MB was my estimate; real columns with repeated values will do better,
  unique strings worse). Retention and disk budget are the maintainer's / the platform module's call.
- Export after a bulk write is the slow part (22.5 s): every cell of the rectangle is regenerated (`cell_xml`) and every
  rebuilt row is re-parsed twice (cell offsets, then the well-formedness check). That is a job, not a request;
  it is exactly what progress/cancel (CC-13) is for. No optimization was attempted.
- Bulk writes track dirtiness as rectangles (`bulk_rects`), not per cell, so undoing a bulk write does **not** make
  the sheet byte-identical to the file again (the rectangle stays dirty and is regenerated with equal content);
  per-cell edits still do.
