# Engine benchmarks

Only numbers from actual runs are recorded here. Re-run: `python benchmarks/bench_csv_100k.py`.
Targets in docs/TESTING_STRATEGY.md are hypotheses; this file only reports what was measured.

## E1 — CSV import / window read / export, 100,000 rows x 20 columns

Environment: Python 3.12.3, Linux container, **1 CPU**, glibc 2.39, commit of branch
`agent1/e1-csv-store`. Deterministic generated file (seed 1234): numbers, decimals, Persian text,
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
  which is Agent 0's/Agent 3's call to budget (cap is `max_patch_cells`, default 200,000).
- Sheets that contain shared or array formulas are loaded completely on the first edit (so the
  protection check sees every formula group): ~11-13 s for a 100k x 20 sheet of this kind. The
  benchmark file has none.
