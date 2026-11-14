# Benchmarks: 100,000 rows x 20 columns

Status: **measured once, on one small machine; treat as order-of-magnitude evidence, not as a guarantee.** The performance budgets in `docs/TESTING_STRATEGY.md` are *targets to be validated*; this file is the validation attempt for the dataops package only (not the UI, not the real engine).

## How to reproduce
```
pip install -e ../../contracts/python -e '.[dev]'
python benchmarks/run.py --rows 100000 --sheet-rows 10000 --runs 5 [--only "sort"] [--out results.json]
```
`benchmarks/generate.py` creates the data: seeded (`20261113`), deterministic, 100,000 rows x 20 columns (3 int-like, 4 float-like, bool, 2 dates, 1 datetime, Persian names with Arabic-variant letters, ZWNJ, Persian digits with thousands separators, Jalali date text, comma-separated tags...), ~10% nulls, ~10% exact duplicate rows, plus a 10,001-row table for the join. Main table on disk: 4.8 MB (zstd Parquet).

Method: every row below ran in a **fresh subprocess** (so peak RSS belongs to that case), through the **public executor and the real `ParquetTableStore`** (not internal functions). One warm-up call, then 5 timed calls; **median and worst** are reported. Each call gets a pristine copy of the input (a new table, or a restored in-memory grid), so destructive operations are always measured on the same data. "apply" includes reading the Parquet version, validation, planning, writing a new immutable version (or a new table) and updating the index. "preview" is `preview(op, ctx, limit=100)`, which computes the full plan and returns 100 rows.

## Environment (the only one measured)
| | |
|---|---|
| Commit | branch `agent2/m5-benchmarks` on top of `102aefa` |
| CPU / RAM | Intel Xeon @ 2.1 GHz, **1 core**, 4 GB (sandbox VM, not reference hardware) |
| Disk | local virtual disk (ext4) |
| Software | Python 3.12.3, polars 2.1.0 |

## Results: data tables (100,000 rows x 20 columns)
| Operation | preview s | apply median s | apply worst s | peak RSS MB |
|---|---:|---:|---:|---:|
| Parquet read + write of a new version (no operation) | - | 0.206 | 0.212 | 209 |
| sort (Persian text + number) | 0.142 | 0.434 | 0.505 | 210 |
| sort (binary text) | 0.112 | 0.310 | 0.399 | 210 |
| filter (and/or groups, text + number) | 0.054 | 0.070 | 0.071 | 210 |
| remove_duplicates (all columns) | 0.322 | 0.479 | 0.520 | 285 |
| remove_duplicates (2 columns, variant-insensitive) | 0.100 | 0.115 | 0.143 | 209 |
| change_type (Persian digits text -> int64) | 0.699 | 0.997 | 1.067 | 211 |
| find_replace (3 text columns, variant-insensitive) | 0.057 | 0.224 | 0.269 | 211 |
| fill (down, all columns) | 0.082 | 0.251 | 0.309 | 210 |
| clean_text (all text columns, all Persian options) | 0.560 | 0.791 | 0.870 | 211 |
| split_column (delimiter) | 0.122 | 0.313 | 0.323 | 211 |
| merge_columns (3 columns) | 0.127 | 0.314 | 0.363 | 210 |
| computed_column (arithmetic + if) | 0.049 | 0.249 | 0.302 | 210 |
| group_aggregate (10k keys, 4 aggregates) | 0.059 | 0.087 | 0.109 | 210 |
| group_aggregate (city, Persian-sorted groups) | 0.055 | 0.044 | 0.081 | 210 |
| pivot (10k keys x 8 columns) | 0.079 | 0.076 | 0.091 | 210 |
| unpivot (5 value columns -> 500k rows) | 0.054 | 0.201 | 0.234 | 210 |
| join (100k x 10k keys, left) | 0.061 | 0.284 | 0.389 | 210 |
| convert_calendar (to Jalali) | 0.102 | 0.279 | 0.402 | 210 |
| convert_calendar (from Jalali) | 0.093 | 0.324 | 0.418 | 210 |
| chart_data (sum by 8 categories) | - | 0.042 | 0.049 | 209 |
| **pipeline of 5 steps** (clean_text, remove_duplicates, change_type, sort, fill) | - | **3.813** | 4.314 | 331 |

(Preview can be larger than apply for cheap operations because the first few calls in a process include one-off costs that the warm-up only partly removes; read both columns as "about this long".)

## Results: sheet ranges (10,000 rows x 19 supported columns = 190,019 cells, in-memory test double)
| Operation | preview s | apply median s | apply worst s | peak RSS MB |
|---|---:|---:|---:|---:|
| sort (Persian text + number) | 0.573 | 4.699 | 5.076 | 654 |
| remove_duplicates (all columns) | 0.409 | 4.293 | 4.793 | 633 |
| change_type (Persian digits text -> int64) | 0.500 | 2.260 | 2.507 | 467 |
| find_replace (3 text columns) | 0.541 | 1.970 | 2.278 | 446 |
| clean_text (all text columns, Persian options) | 0.620 | 1.970 | 2.505 | 471 |
| computed_column (arithmetic + if) | 0.463 | 2.499 | 2.629 | 465 |
| chart_data (sum by 8 categories) | - | 0.563 | 0.631 | 353 |
| pipeline of 5 steps | - | 17.847 | 21.277 | 1081 |

**These sheet numbers do not include the real engine and are not at 100k rows.** A 100k x 20 sheet is 2,000,000 cells; with the test double (pydantic `Cell` objects) that does not fit comfortably in 4 GB, and the default per-patch cap (200,000 cells) would refuse it anyway, so the sheet column was measured at 10,000 rows.

## Where the sheet time goes (profile of `sort`, same 10,000 rows)
| Step | seconds |
|---|---:|
| Polars plan (the actual sort) | 0.012 |
| `read_range` of the test double | 0.16 |
| adapter: cells -> typed columns | ~0.55 |
| adapter: columns -> cell values | ~0.80 |
| `write_range` of the test double (diff of 190k cells with pydantic equality) | ~4.2 |

So the dataops adapter costs about **7 microseconds per cell** (~1.35 s for 190k cells); the rest is the test double and says nothing about the real engine. Extrapolating the adapter alone to 2,000,000 cells gives roughly 14 s (an extrapolation, not a measurement). The Polars part is negligible.

## Reading against the stated budget
- "Sort/filter/dedupe at 100k rows: interactive (seconds)": **met on data tables** on this machine (apply 0.07 to 0.5 s; preview 0.05 to 0.3 s). Not demonstrated on sheet ranges: the cell-by-cell conversion between `ExecContext` and Polars is the bottleneck there, and the engine's own cost is unmeasured.
- Memory: about 210 MB per 100k x 20 table operation (285 MB for full-row dedupe, 331 MB for the 5-step pipeline).
- The 5-step table pipeline takes 3.8 s because every step re-reads and re-writes a Parquet version (this is the "no in-memory hand-off between committed steps" limitation in the README); 0.2 s of that per step is the Parquet round trip measured in the first row.

## Findings and suggested follow-ups (not done)
1. **A columnar path for sheet ranges** would remove the dominant dataops cost: e.g. an engine API that returns/accepts a range as typed columns (Arrow-like) instead of `list[list[Cell]]`. This needs a contract decision (Agent 0/Agent 1); I have not changed anything.
2. In-memory hand-off between pipeline steps (keep the frame, write one version per step at the end) would cut the pipeline time roughly in half but needs care to keep per-step deltas and rollback exact.
3. Measure on reference hardware with more than one core before quoting any number outside this repository.

## Known limits of this measurement
Single machine, single core, small RAM; synthetic data (Persian-heavy text, 10% nulls, 10% duplicates); 5 runs per case; times can vary by a few tens of percent between runs (compare the worst column); the join benchmark uses ~10 matches per key; larger-than-memory data was not tested.
