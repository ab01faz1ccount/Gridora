"""Before/after of the columnar sheet path: same operations, same 10,000 x 19 sheet, row-major vs columnar.

    python benchmarks/sheet_paths.py [--rows 10000] [--runs 5]

Doubles: see doubles.py. "A" = adapter only, "B" = adapter + the interface objects an engine must build/parse.
The full test double of tests/fakes.py (pydantic diff of every cell) is reported too, because it is what the earlier
BENCHMARKS.md numbers used.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tests")]

import polars as pl
from doubles import LeanColumnarContext, LeanRowContext
from generate import generate
from gridora_contracts.models import Operation, Range, SheetRangeTarget

from gridora_dataops import DataOpsExecutor

CASES = [
    ("sort (Persian text + number)", "sort", {"keys": [{"column": "name"}, {"column": "price", "direction": "desc"}]}),
    ("remove_duplicates (all columns)", "remove_duplicates", {}),
    ("change_type (Persian digits -> int64)", "change_type", {"column": "amount_text", "to": "int64"}),
    ("find_replace (3 text columns)", "find_replace", {"columns": ["name", "city", "note"], "find": "علی", "replace": "X", "ignore_variants": True}),
    ("fill (down, all columns)", "fill", {"mode": "down"}),
    ("clean_text (all text, Persian options)", "clean_text", {"arabic_letters_to_persian": True, "digits": "to_latin", "zwnj": "remove"}),
    ("convert_calendar (to Jalali, replace)", "convert_calendar", {"column": "created", "digits": "persian"}),
    ("split_column (grows: header changes)", "split_column", {"column": "tags", "delimiter": ","}),
    ("computed_column (grows: header changes)", "computed_column", {"name": "total", "expr": {"kind": "call", "fn": "mul", "args": [
        {"kind": "col", "name": "qty"}, {"kind": "col", "name": "price"}]}}),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10_000)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--only", help="substring filter on the operation label")
    a = ap.parse_args()
    df = generate(a.rows)
    keep = [c for c in df.columns if df.schema[c] in (pl.String, pl.Int64, pl.Float64, pl.Boolean, pl.Date)]
    sub = df.select(keep)
    rng = Range(sheet_id="s1", r0=0, c0=0, r1=sub.height, c1=sub.width - 1)
    print(f"{sub.height} rows x {sub.width} columns = {(sub.height + 1) * sub.width} cells; median of {a.runs} (worst in brackets), seconds")
    print(f"{'operation':42} {'A row':>14} {'A columnar':>14} {'gain':>6} | {'B row':>14} {'B columnar':>14} {'gain':>6}")

    def timed(ctx_cls, mode, type_, params, columnar):  # type: ignore[no-untyped-def]
        ex = DataOpsExecutor(columnar=columnar, max_patch_cells=10**9)
        op = Operation(type=type_, target=SheetRangeTarget(range=rng), params=params)
        ctx = ctx_cls(sub, mode)
        assert ex.apply(op, ctx).status == "ok"  # warm-up (and correctness)
        out = []
        for _ in range(a.runs):
            ctx = ctx_cls(sub, mode)
            t0 = time.perf_counter()
            ex.apply(op, ctx)
            out.append(time.perf_counter() - t0)
        return statistics.median(out), max(out)

    for label, type_, params in CASES:
        if a.only and a.only not in label:
            continue
        cells = []
        for mode in ("A", "B"):
            r = timed(LeanRowContext, mode, type_, params, False)
            c = timed(LeanColumnarContext, mode, type_, params, True)
            cells += [r, c]
        (ar, ac, br, bc) = cells
        print(f"{label:42} {ar[0]:7.3f}({ar[1]:.3f}) {ac[0]:7.3f}({ac[1]:.3f}) {ar[0] / ac[0]:5.1f}x | "
              f"{br[0]:7.3f}({br[1]:.3f}) {bc[0]:7.3f}({bc[1]:.3f}) {br[0] / bc[0]:5.1f}x")


if __name__ == "__main__" and "--full-double" not in sys.argv:
    main()


def full_double(rows: int, runs: int, only: str | None) -> None:
    """The FULL test double (tests/fakes.py): every written cell is diffed with pydantic equality, like a naive engine."""
    from fakes import ColumnarFakeExecContext, RowFakeExecContext

    from gridora_dataops.targets import to_cell_rows
    df = generate(rows)
    sub = df.select([c for c in df.columns if df.schema[c] in (pl.String, pl.Int64, pl.Float64, pl.Boolean, pl.Date)])
    grid = to_cell_rows(sub, list(sub.columns))
    print(f"full test double, {sub.height} rows x {sub.width} columns; median of {runs} (worst), seconds")
    print(f"{'operation':42} {'row':>16} {'columnar':>16} {'gain':>6}")

    def make(cls):  # type: ignore[no-untyped-def]
        ctx = cls()
        ctx.fill(grid)
        return ctx

    protos = {c: make(c) for c in (RowFakeExecContext, ColumnarFakeExecContext)}
    rng = Range(sheet_id="s1", r0=0, c0=0, r1=sub.height, c1=sub.width - 1)
    for label, type_, params in CASES[:7]:
        if only and only not in label:
            continue
        res = []
        for cls, columnar in ((RowFakeExecContext, False), (ColumnarFakeExecContext, True)):
            ex = DataOpsExecutor(columnar=columnar, max_patch_cells=10**9)
            op = Operation(type=type_, target=SheetRangeTarget(range=rng), params=params)
            times = []
            for i in range(runs + 1):
                ctx = cls()
                ctx.grid = dict(protos[cls].grid)
                t0 = time.perf_counter()
                assert ex.apply(op, ctx).status == "ok"
                if i:
                    times.append(time.perf_counter() - t0)
            res.append((statistics.median(times), max(times)))
        (r, c) = res
        print(f"{label:42} {r[0]:8.3f}({r[1]:.3f}) {c[0]:8.3f}({c[1]:.3f}) {r[0] / c[0]:5.1f}x")


if __name__ == "__main__" and "--full-double" in sys.argv:
    sys.argv.remove("--full-double")
    _a = argparse.ArgumentParser()
    _a.add_argument("--rows", type=int, default=10_000)
    _a.add_argument("--runs", type=int, default=3)
    _a.add_argument("--only")
    _x = _a.parse_args()
    full_double(_x.rows, _x.runs, _x.only)
    sys.exit(0)
