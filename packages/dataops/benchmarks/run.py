"""100k-row performance run through the PUBLIC executor/store (not internal functions).

    python benchmarks/run.py [--rows 100000] [--sheet-rows 10000] [--runs 5] [--out results.json]

Method: data is generated once (seeded) and written as Parquet; every operation runs in a FRESH subprocess
(so peak RSS is that operation's own), one warm-up call, then `--runs` timed calls; median and worst are reported.
Table targets use the real ParquetTableStore on local disk. Sheet targets use the in-memory test double
(tests/fakes.py), so the numbers EXCLUDE the real engine's cost and use a smaller range (`--sheet-rows`):
a 100k x 20 sheet is 2,000,000 cells, which neither the default 200,000-cell patch cap nor a 3 GB machine allows
with the pydantic-based test double.
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tests")]

TABLE = "t0"


def op_table(type_: str, **params):  # type: ignore[no-untyped-def]
    return {"type": type_, "params": params}


def cond(column, op, value=None, **kw):  # type: ignore[no-untyped-def]
    return {"kind": "condition", "column": column, "op": op, "value": value, **kw}


CASES: dict[str, dict] = {  # type: ignore[type-arg]
    "sort (persian text + number)": op_table("sort", keys=[{"column": "name"}, {"column": "price", "direction": "desc"}]),
    "sort (binary text)": op_table("sort", keys=[{"column": "email"}], collation="binary"),
    "filter (and/or, text+number)": op_table("filter", where={"kind": "group", "logic": "and", "items": [
        cond("price", "between", 100, value2=600), {"kind": "group", "logic": "or", "items": [
            cond("city", "contains", "ران"), cond("qty", "gt", 90)]}]}),
    "remove_duplicates (all columns)": op_table("remove_duplicates"),
    "remove_duplicates (key, variants)": op_table("remove_duplicates", columns=["name", "city"], ignore_variants=True),
    "change_type (persian digits -> int64)": op_table("change_type", column="amount_text", to="int64"),
    "find_replace (variants, 3 text cols)": op_table("find_replace", columns=["name", "city", "note"], find="علی", replace="X", ignore_variants=True),
    "fill (down, all columns)": op_table("fill", mode="down"),
    "clean_text (all text, persian options)": op_table("clean_text", arabic_letters_to_persian=True, digits="to_latin",
                                                       remove_tatweel=True, zwnj="remove", remove_diacritics=True),
    "split_column (delimiter)": op_table("split_column", column="tags", delimiter=","),
    "merge_columns (3 columns)": op_table("merge_columns", columns=["name", "city", "qty"], separator=" - "),
    "computed_column (arithmetic + if)": op_table("computed_column", name="total", expr={"kind": "call", "fn": "if", "args": [
        {"kind": "call", "fn": "gt", "args": [{"kind": "col", "name": "qty"}, {"kind": "lit", "value": 50}]},
        {"kind": "call", "fn": "mul", "args": [{"kind": "col", "name": "qty"}, {"kind": "col", "name": "price"}]},
        {"kind": "lit", "value": 0}]}),
    "group_aggregate (key, 4 aggregates)": op_table("group_aggregate", by=["key"], aggregations=[
        {"fn": "sum", "column": "price"}, {"fn": "avg", "column": "score"}, {"fn": "count"}, {"fn": "max", "column": "qty"}]),
    "group_aggregate (city, persian sorted)": op_table("group_aggregate", by=["city"], sort_groups=True,
                                                       aggregations=[{"fn": "sum", "column": "price"}]),
    "pivot (key x city)": op_table("pivot", index=["key"], columns="group8", values="qty", fn="sum"),
    "unpivot (5 value columns)": op_table("unpivot", id_columns=["key"], value_columns=["qty", "price", "score", "ratio", "id"]),
    "join (100k x 10k keys, left)": op_table("join", how="left", left_on=["key"], right_on=["key"]),
    "convert_calendar (to jalali)": op_table("convert_calendar", column="created", digits="persian"),
    "convert_calendar (from jalali)": op_table("convert_calendar", column="jalali_text", direction="from_jalali", on_error="null"),
}


def child(case: str, mode: str, rows: int, runs: int, data: Path) -> None:
    import polars as pl
    from fakes import FakeExecContext
    from gridora_contracts.models import (
        ChartSeries,
        ChartSpec,
        DataTableTarget,
        Operation,
        Pipeline,
        PipelineStep,
        SheetRangeTarget,
    )

    from gridora_dataops import DataOpsExecutor, create_table_store

    store_root = Path(tempfile.mkdtemp(prefix="gridora-bench-"))
    ids = iter(f"t{i}" for i in range(10_000))
    store = create_table_store(lambda o, t, v: store_root / o / t / f"v{v}.parquet", new_id=ids.__next__)
    ctx = FakeExecContext(store=store)
    ex = DataOpsExecutor(max_patch_cells=10**9)
    left = pl.read_parquet(data / "main.parquet")
    store.create_table("u1", "w1", "main", left)                                       # t0 (the pristine copy)
    store.create_table("u1", "w1", "right", pl.read_parquet(data / "right.parquet"))   # t1
    orig_grid: dict = {}  # type: ignore[type-arg]

    if mode == "sheet":  # smaller range in the in-memory double; strings/numbers/bools/dates only
        from gridora_contracts.models import Cell

        from gridora_dataops.targets import to_cell_rows
        sub = left.head(rows).select([c for c in left.columns if left.schema[c] in (pl.String, pl.Int64, pl.Float64, pl.Boolean, pl.Date)])
        grid = to_cell_rows(sub, list(sub.columns))
        for r, row in enumerate(grid):
            for c, v in enumerate(row):
                if v is not None:
                    orig_grid[(r, c)] = Cell(r=r, c=c, v=v)
        sheet_target = SheetRangeTarget(range=ctx.rng(0, 0, len(grid) - 1, sub.width - 1))

    def fresh():  # type: ignore[no-untyped-def]
        """A pristine target for every call, so destructive operations are measured on the same input each time."""
        if mode == "sheet":
            ctx.grid = dict(orig_grid)
            return sheet_target
        tid = store.create_table("u1", "w1", "copy", left).id
        return DataTableTarget(table_id=tid)

    def timed(fn):  # type: ignore[no-untyped-def]
        fn(fresh())  # warm-up
        out = []
        for _ in range(runs):
            tgt = fresh()
            t0 = time.perf_counter()
            fn(tgt)
            out.append(time.perf_counter() - t0)
        return out

    preview_med = None
    if case == "__io__":
        def work(t):  # type: ignore[no-untyped-def]
            frame, v = store.read_frame("u1", t.table_id)
            store.write_version("u1", t.table_id, frame, parent=v)
        times = timed(work)
    elif case == "__chart__":
        def work(t):  # type: ignore[no-untyped-def]
            ex.chart_data(ChartSpec(document_id="d", type="bar", source=t, series=[
                ChartSeries(value_col="price", category_col="city", aggregate="sum")]), ctx)
        times = timed(work)
    elif case == "__pipeline__":
        def work(t):  # type: ignore[no-untyped-def]
            p = Pipeline(name="p", input_kind=t.kind, steps=[PipelineStep(type="clean_text", params={}),
                PipelineStep(type="remove_duplicates", params={}),
                PipelineStep(type="change_type", params={"column": "amount_text", "to": "int64"}),
                PipelineStep(type="sort", params={"keys": [{"column": "name"}]}),
                PipelineStep(type="fill", params={"mode": "down"})])
            res = ex.run_pipeline(p, t, ctx)
            if any(r.status != "ok" for r in res):
                raise RuntimeError(str([r.errors for r in res]))
        times = timed(work)
    else:
        spec = CASES[case]

        def mk(t):  # type: ignore[no-untyped-def]
            extra = [DataTableTarget(table_id="t1")] if spec["type"] == "join" else []
            return Operation(type=spec["type"], target=t, extra_targets=extra, params=spec["params"])

        def work(t):  # type: ignore[no-untyped-def]
            res = ex.apply(mk(t), ctx)
            if res.status != "ok":
                raise RuntimeError(str(res.errors))
        times = timed(work)
        pv = []
        ex.preview(mk(fresh()), ctx, 100)  # warm-up
        for _ in range(runs):
            tgt = fresh()
            t0 = time.perf_counter()
            ex.preview(mk(tgt), ctx, 100)
            pv.append(time.perf_counter() - t0)
        preview_med = statistics.median(pv)
    print(json.dumps({"preview_s": preview_med, "median_s": statistics.median(times), "worst_s": max(times),
                      "rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--sheet-rows", type=int, default=10_000)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out")
    ap.add_argument("--only", help="substring filter on case names")
    ap.add_argument("--child", nargs=2, metavar=("CASE", "MODE"))
    ap.add_argument("--data")
    a = ap.parse_args()
    if a.child:
        child(a.child[0], a.child[1], a.rows if a.child[1] == "table" else a.sheet_rows, a.runs, Path(a.data))
        return
    import polars as pl
    from generate import generate, generate_right
    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        t0 = time.perf_counter()
        generate(a.rows).write_parquet(data / "main.parquet", compression="zstd")
        generate_right(a.rows).write_parquet(data / "right.parquet", compression="zstd")
        print(f"generated {a.rows} rows x 20 columns in {time.perf_counter() - t0:.1f}s; "
              f"main.parquet {(data / 'main.parquet').stat().st_size / 1e6:.1f} MB")
        results = {}
        cases = [("__io__", "table"), ("__pipeline__", "table"), ("__chart__", "table")]
        cases += [(c, "table") for c in CASES]
        cases += [(c, "sheet") for c in ("sort (persian text + number)", "remove_duplicates (all columns)", "change_type (persian digits -> int64)",
                                         "clean_text (all text, persian options)", "computed_column (arithmetic + if)",
                                         "find_replace (variants, 3 text cols)", "__pipeline__", "__chart__")]
        print(f"{'case':44} {'target':6} {'preview':>8} {'median':>8} {'worst':>8} {'rss MB':>7}")
        for case, mode in cases:
            if a.only and a.only not in case:
                continue
            p = subprocess.run([sys.executable, __file__, "--child", case, mode, "--rows", str(a.rows),
                                "--sheet-rows", str(a.sheet_rows), "--runs", str(a.runs), "--data", str(data)],
                               check=False, capture_output=True, text=True)
            if p.returncode != 0:
                msg = (p.stderr.strip().splitlines() or ["?"])[-1]
                print(f"{case:44} {mode:6} FAILED: {msg[:120]}")
                results[f"{case} [{mode}]"] = {"error": msg}
                continue
            r = json.loads(p.stdout.strip().splitlines()[-1])
            results[f"{case} [{mode}]"] = r
            pv = f"{r['preview_s']:.3f}" if r["preview_s"] is not None else "-"
            print(f"{case:44} {mode:6} {pv:>8} {r['median_s']:8.3f} {r['worst_s']:8.3f} {r['rss_mb']:7.0f}")
        if a.out:
            Path(a.out).write_text(json.dumps({"rows": a.rows, "sheet_rows": a.sheet_rows, "runs": a.runs, "results": results,
                                               "python": platform.python_version(), "polars": pl.__version__}, indent=1))


if __name__ == "__main__":
    main()
