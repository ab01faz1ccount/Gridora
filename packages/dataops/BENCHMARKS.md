# Benchmarks: 100,000 rows x 20 columns

Status: **measured once, on one small machine; treat as order-of-magnitude evidence, not as a guarantee.** The performance budgets in `docs/TESTING_STRATEGY.md` are *targets to be validated*; this file is the validation attempt for the dataops package only (not the UI, not the real engine).

## How to reproduce
```
pip install -e ../../contracts/python -e '.[dev]'
python benchmarks/run.py --rows 100000 --sheet-rows 10000 --runs 5 [--only "sort"] [--out results.json]
```
`benchmarks/generate.py` creates the data: seeded (`20261113`), deterministic, 100,000 rows x 20 columns (3 int-like, 4 float-like, bool, 2 dates, 1 datetime, Persian names with Arabic-variant letters, ZWNJ, Persian digits with thousands separators, Jalali date text, comma-separated tags...), ~10% nulls, ~10% exact duplicate rows, plus a 10,001-row table for the join. Main table on disk: 4.8 MB (zstd Parquet).

Command used for the final numbers (in batches, because one long run was killed by the sandbox): `python benchmarks/run.py --rows 100000 --sheet-rows 10000 --runs 5 --only "<case>" [--mode table|sheet]`.

Method: every row below ran in a **fresh subprocess** (so peak RSS belongs to that case), through the **public executor and the real `ParquetTableStore`** (not internal functions). One warm-up call, then 5 timed calls; **median and worst** are reported. Each call gets a pristine copy of the input (a new table, or a restored in-memory grid), so destructive operations are always measured on the same data. "apply" includes reading the Parquet version, validation, planning, writing a new immutable version (or a new table) and updating the index. "preview" is `preview(op, ctx, limit=100)`, which computes the full plan and returns 100 rows.

## Environment (the only one measured)
| | |
|---|---|
| Commit | branch `agent2/m5-benchmarks` rebased on main `bf02d63` (contracts 0.3.0) |
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

## Results: sheet ranges, every operation (10,000 rows x 19 supported columns = 190,019 cells, in-memory test double)
Second, complete run (all 15 operations plus chart and pipeline). An earlier partial run measured some in-place cases 20-50% slower (for example sort 4.7 s against 3.1 s here): on this shared 1-core VM, **repeat-to-repeat variation is of that order**, so read these as "a few seconds", not as precise figures.

| Operation | preview s | apply median s | apply worst s | peak RSS MB |
|---|---:|---:|---:|---:|
| *in place on the range (one `write_range`, one delta)* | | | | |
| sort (Persian text + number) | 0.419 | 3.136 | 3.607 | 653 |
| sort (binary text) | 0.282 | 3.519 | 3.714 | 652 |
| remove_duplicates (all columns) | 0.308 | 3.073 | 3.369 | 635 |
| remove_duplicates (2 columns, variants) | 0.406 | 1.607 | 1.652 | 468 |
| change_type (Persian digits text -> int64) | 0.375 | 1.478 | 1.737 | 458 |
| find_replace (3 text columns, variants) | 0.424 | 1.134 | 1.351 | 446 |
| fill (down, all columns) | 0.286 | 1.399 | 1.454 | 478 |
| clean_text (all text columns, Persian options) | 0.436 | 1.761 | 1.892 | 482 |
| split_column (delimiter, grows by columns) | 0.767 | 3.703 | 4.851 | 500 |
| merge_columns (3 columns, grows by one column) | 0.891 | 5.283 | 5.756 | 550 |
| computed_column (arithmetic + if, grows by one column) | 0.431 | 3.531 | 3.559 | 466 |
| convert_calendar (to Jalali, replaces the column) | 0.311 | 1.646 | 1.709 | 460 |
| convert_calendar (from Jalali, replaces the column) | 0.451 | 1.426 | 1.651 | 460 |
| *creates a new table (nothing is written to the sheet)* | | | | |
| filter (and/or groups, text + number) | 0.269 | 0.279 | 0.413 | 355 |
| group_aggregate (10k keys, 4 aggregates) | 0.317 | 0.379 | 0.692 | 355 |
| group_aggregate (city, Persian-sorted groups) | 0.403 | 0.410 | 0.664 | 356 |
| pivot (10k keys x 8 columns) | 0.342 | 0.401 | 0.655 | 357 |
| unpivot (5 value columns) | 0.323 | 0.358 | 0.663 | 357 |
| join (with a 10k-key table, left) | 0.380 | 0.502 | 0.550 | 360 |
| chart_data (sum by 8 categories) | - | 0.315 | 0.581 | 354 |
| **pipeline of 5 steps** | - | **14.254** | 14.494 | 1081 |

**These sheet numbers do not include the real engine, and they are not at 100,000 rows. This is by design, not an omission:** contract decision CC-11 (ADR-013) caps one patch at **200,000 cells**, so an in-place operation on a sheet range can never touch more than about 10,000 rows x 20 columns. A 100,000 x 20 sheet is 2,000,000 cells; operations on it are refused with `too_large_for_history` (and the in-memory test double could not hold it in 4 GB anyway). The 100,000-row figures are therefore the data-table results above. Operations that create a new table read the range but write nothing back, which is why they are 5-10 times faster here than the in-place ones.

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
- "Sort/filter/dedupe at 100k rows: interactive (seconds)": **met on data tables** on this machine (apply 0.07 to 0.5 s; preview 0.05 to 0.3 s). On sheet ranges (at most ~190k cells because of the patch cap) in-place operations take about 1 to 5 s with the test double; most of that is cell-by-cell conversion and the double's own `write_range`, and the real engine's cost is unmeasured, so "interactive on sheets" is **not demonstrated**.
- Memory: about 210 MB per 100k x 20 table operation (285 MB for full-row dedupe, 331 MB for the 5-step pipeline).
- The 5-step table pipeline takes 3.8 s because every step re-reads and re-writes a Parquet version (this is the "no in-memory hand-off between committed steps" limitation in the README); 0.2 s of that per step is the Parquet round trip measured in the first row.

## Findings and suggested follow-ups (not done)
1. **A columnar path for sheet ranges** would remove the dominant dataops cost: e.g. an engine API that returns/accepts a range as typed columns (Arrow-like) instead of `list[list[Cell]]`. This needs a contract decision (Agent 0/Agent 1); I have not changed anything.
2. In-memory hand-off between pipeline steps (keep the frame, write one version per step at the end) would cut the pipeline time roughly in half but needs care to keep per-step deltas and rollback exact.
3. Measure on reference hardware with more than one core before quoting any number outside this repository.

## Known limits of this measurement
Single machine, single core, small RAM; synthetic data (Persian-heavy text, 10% nulls, 10% duplicates); 5 runs per case; times can vary by a few tens of percent between runs (compare the worst column); the join benchmark uses ~10 matches per key; larger-than-memory data was not tested.
