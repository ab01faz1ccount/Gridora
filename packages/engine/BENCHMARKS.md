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
