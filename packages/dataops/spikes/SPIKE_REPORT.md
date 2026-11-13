# M0 spike — Polars vs DuckDB (join / group / pivot / decimal)

Status: **measured, small scale.** Script: `polars_vs_duckdb.py` (seeded, deterministic). Not production code.

## Setup (exact)
- Command: `python packages/dataops/spikes/polars_vs_duckdb.py` (100,000 rows, 5 runs after 1 warm-up, one fresh subprocess per engine/workload).
- Versions: Python 3.12.3, polars 2.1.0, duckdb 2.0.0.
- Hardware: Intel Xeon @ 2.1 GHz, **1 core, 3 GB RAM** (sandbox VM, not reference hardware). DuckDB limited to 1 thread.
- Data: left table 100k rows (id, key with ~10 rows/key, 6 Persian category values, amount with 10% nulls, qty); right table ~10k keys (80% overlap with left + extra keys). Parquet, zstd.
- DuckDB results are handed to Polars **through Parquet**, because DuckDB's Arrow path requires `pyarrow` (an extra dependency we would otherwise not need). That hand-off cost is included in the DuckDB numbers.

## Results (median seconds / peak RSS MB)
| Workload | Polars | DuckDB | Same result? |
|---|---|---|---|
| inner join (80,016 rows) | 0.012 / 94 | 0.068 / 146 | yes (row count + order hash) |
| left join (100,000) | 0.015 / 98 | 0.117 / 151 | yes |
| full join (101,000) | 0.014 / 100 | 0.088 / 152 | yes |
| group + sum/mean/count (6 rows) | 0.003 / 94 | 0.019 / 94 | yes (same sums) |
| pivot (10,000 x 7) | 0.016 / 94 | 0.033 / 125 | yes |
| decimal(18,2) Parquet round trip | 0.010 | 0.026 | yes (same sum; type kept as Decimal(18,2)) |

## Findings
1. At 100k rows Polars was faster on every workload and used no more memory. Results (row counts, ordering, sums) were identical when both sides used explicit ordering.
2. DuckDB adds a dependency plus a second set of null/type/ordering semantics, and needs a Parquet round trip (or `pyarrow`) to return data to Polars.
3. Polars' decimal type kept precision and scale through a Parquet round trip in this version (2.1.0). This answers Agent 0's Q1 for this version only; M2 tests must pin it.
4. Not tested: data larger than memory (where DuckDB's out-of-core joins could win), multi-core machines, wide tables, string-heavy join keys with collation. The numbers above say nothing about those cases.

## Recommendation (for Agent 0 to record in DECISIONS.md)
**Polars-only for v1.** Do not add `duckdb` now. Revisit only if a measured case (e.g. a join that exceeds memory) fails with Polars. Dependencies for M0: `polars` (exact pin in the lockfile once the real versions are agreed), dev: `pytest`, `hypothesis`, `jsonschema`, `ruff`, `mypy`. Licenses must be verified by Agent 0 at the dependency review; I have not verified them.
