"""M0 spike: Polars vs DuckDB for join / group_aggregate / pivot / decimal at 100k rows.

Run:  python packages/dataops/spikes/polars_vs_duckdb.py [--rows 100000] [--runs 5]
Each (engine, workload) runs in a fresh subprocess so peak RSS is meaningful.
Not production code; results are recorded in SPIKE_REPORT.md.
"""
from __future__ import annotations

import argparse
import json
import random
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKLOADS = ["join_inner", "join_left", "join_full", "group_agg", "pivot", "decimal_roundtrip"]


def generate(root: Path, rows: int) -> None:
    import polars as pl

    rnd = random.Random(20261113)
    keys = [f"k{n:05d}" for n in range(rows // 10)]  # ~10 rows per key
    left = pl.DataFrame(
        {
            "id": list(range(rows)),
            "key": [rnd.choice(keys) for _ in range(rows)],
            "cat": [rnd.choice(["الف", "ب", "پ", "ت", "ج", "چ"]) for _ in range(rows)],
            "amount": [None if rnd.random() < 0.1 else round(rnd.random() * 1000, 2) for _ in range(rows)],
            "qty": [rnd.randint(1, 50) for _ in range(rows)],
        }
    )
    right_keys = keys[: int(len(keys) * 0.8)] + [f"x{n:05d}" for n in range(len(keys) // 10)]
    right = pl.DataFrame(
        {"key": right_keys, "label": [f"lbl{n}" for n in range(len(right_keys))]}
    )
    left.write_parquet(root / "left.parquet", compression="zstd")
    right.write_parquet(root / "right.parquet", compression="zstd")


def run_polars(workload: str, root: Path):
    import polars as pl

    left = pl.scan_parquet(root / "left.parquet")
    right = pl.scan_parquet(root / "right.parquet")
    if workload.startswith("join_"):
        how = workload.split("_")[1]
        out = left.join(right, on="key", how=how, coalesce=True).sort(["id", "key"], nulls_last=True).collect()
        return out.height, hash(tuple(out["id"].head(1000).to_list()))
    if workload == "group_agg":
        out = (
            left.group_by("cat", maintain_order=False)
            .agg(pl.col("amount").sum().alias("s"), pl.col("amount").mean().alias("m"), pl.len().alias("n"))
            .sort("cat")
            .collect()
        )
        return out.height, round(out["s"].sum(), 2)
    if workload == "pivot":
        out = left.collect().pivot(on="cat", index="key", values="qty", aggregate_function="sum").sort("key")
        return out.height, out.width
    if workload == "decimal_roundtrip":
        df = left.select(pl.col("amount").cast(pl.Decimal(18, 2)).alias("d")).collect()
        p = root / "dec.parquet"
        df.write_parquet(p)
        back = pl.read_parquet(p)
        s = back.select(pl.col("d").sum()).item()
        return back.height, str(s) + "|" + str(back.schema["d"])
    raise ValueError(workload)


def _duck_to_polars(con, query: str, root: Path):
    """DuckDB result -> Polars via Parquet (DuckDB's Arrow path needs pyarrow, an extra dependency)."""
    import polars as pl

    out = root / "duck_out.parquet"
    con.execute(f"COPY ({query}) TO '{out}' (FORMAT PARQUET)")
    return pl.read_parquet(out)


def run_duckdb(workload: str, root: Path):
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    L, R = f"'{root}/left.parquet'", f"'{root}/right.parquet'"
    if workload.startswith("join_"):
        how = {"inner": "INNER", "left": "LEFT", "full": "FULL OUTER"}[workload.split("_")[1]]
        out = _duck_to_polars(con,
            f"SELECT l.id, COALESCE(l.key, r.key) AS key, l.cat, l.amount, l.qty, r.label "
            f"FROM {L} l {how} JOIN {R} r ON l.key = r.key ORDER BY l.id NULLS LAST, key", root)
        return out.height, hash(tuple(out["id"].head(1000).to_list()))
    if workload == "group_agg":
        rows = con.execute(
            f"SELECT cat, SUM(amount) s, AVG(amount) m, COUNT(*) n FROM {L} GROUP BY cat ORDER BY cat"
        ).fetchall()
        return len(rows), round(sum(r[1] for r in rows), 2)
    if workload == "pivot":
        out = _duck_to_polars(con,
            f"SELECT * FROM (PIVOT (SELECT key, cat, qty FROM {L}) ON cat USING SUM(qty) GROUP BY key) ORDER BY key", root)
        return out.height, out.width
    if workload == "decimal_roundtrip":
        p = root / "dec_duck.parquet"
        con.execute(f"COPY (SELECT CAST(amount AS DECIMAL(18,2)) d FROM {L}) TO '{p}' (FORMAT PARQUET)")
        s, t = con.execute(f"SELECT SUM(d), typeof(d) FROM '{p}' GROUP BY typeof(d)").fetchone()
        return con.execute(f"SELECT COUNT(*) FROM '{p}'").fetchone()[0], str(s) + "|" + t
    raise ValueError(workload)


def child(engine: str, workload: str, root: Path, runs: int) -> None:
    fn = run_polars if engine == "polars" else run_duckdb
    fn(workload, root)  # warm-up
    times, last = [], None
    for _ in range(runs):
        t0 = time.perf_counter()
        last = fn(workload, root)
        times.append(time.perf_counter() - t0)
    print(json.dumps({"median": statistics.median(times), "worst": max(times),
                      "rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                      "result": [str(x) for x in last]}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--child", nargs=2, metavar=("ENGINE", "WORKLOAD"))
    ap.add_argument("--root")
    a = ap.parse_args()
    if a.child:
        child(a.child[0], a.child[1], Path(a.root), a.runs)
        return
    import duckdb, polars  # noqa: E401
    print(f"polars {polars.__version__}  duckdb {duckdb.__version__}  rows={a.rows} runs={a.runs}")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        generate(root, a.rows)
        print(f"{'workload':18} {'engine':7} {'median s':>9} {'worst s':>8} {'rss MB':>7}  result")
        for w in WORKLOADS:
            for e in ("polars", "duckdb"):
                p = subprocess.run([sys.executable, __file__, "--child", e, w, "--root", d, "--runs", str(a.runs)],
                                   capture_output=True, text=True)
                if p.returncode != 0:
                    print(f"{w:18} {e:7} FAILED: {p.stderr.strip().splitlines()[-1] if p.stderr else '?'}")
                    continue
                r = json.loads(p.stdout.strip().splitlines()[-1])
                print(f"{w:18} {e:7} {r['median']:9.3f} {r['worst']:8.3f} {r['rss_mb']:7.0f}  {' '.join(r['result'])}")


if __name__ == "__main__":
    main()
