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
