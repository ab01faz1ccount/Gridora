"""E5b-1 benchmark: columnar read of the whole 100k x 20 sheet vs the row-major get_cells path.
Usage: python benchmarks/bench_columnar_100k.py"""
from __future__ import annotations

import os
import platform
import resource
import time
from pathlib import Path

from gridora_contracts.models import ColumnarColumn, ColumnarRange, Range, Window
from xlsx_fixture import build

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError

OUT = Path(__file__).parent / "_out"
ROWS, COLS = 100_000, 20


def t(label: str, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    print(f"{label:<58}{dt:8.2f} s")
    return out, dt


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    src = build(OUT / "big_100k_x_20.xlsx")
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    sid = wb.sheets[0].id
    rng = Range(sheet_id=sid, r0=0, c0=0, r1=ROWS - 1, c1=COLS - 1)
    t("read_range_columnar, whole sheet, cold (includes parsing)", lambda: eng.read_range_columnar(h, rng))
    warm, t_warm = t("read_range_columnar, whole sheet, already parsed", lambda: eng.read_range_columnar(h, rng))
    cells = sum(1 for c in warm.columns for v in c.values if v is not None)
    print(f"  {cells:,} non-empty cells; kinds: {sorted({c.kind for c in warm.columns})}; has_formulas={warm.has_formulas}")
    print(f"  columnar read of parsed data: {t_warm / cells * 1e6:.2f} us per non-empty cell (get_cells path measured earlier: ~7.8 us)")

    def rowmajor() -> int:
        n = 0
        for r0 in range(0, ROWS, 1000):
            for c0 in range(0, COLS, 100):
                n += len(eng.get_cells(h, sid, Window(row0=r0, col0=c0, rows=1000, cols=min(100, COLS - c0))).cells)
        return n

    n, t_rm = t("get_cells over the same range, already parsed", rowmajor)
    print(f"  {n:,} cells: {t_rm / n * 1e6:.2f} us per cell; columnar is {t_rm / t_warm:.1f}x faster on parsed data")
    wr = ColumnarRange(range=rng, columns=[ColumnarColumn(kind=c.kind, values=list(c.values)) for c in warm.columns])
    _delta, _ = t("write_range_columnar of identical data (no changes)", lambda: eng.write_range_columnar(h, rng, wr))
    cols_vals = [list(c.values) for c in warm.columns]
    cols_vals[0] = [None if v is None else v + 1 for v in cols_vals[0]]
    wr2 = ColumnarRange(range=rng, columns=[ColumnarColumn(kind=warm.columns[i].kind, values=cols_vals[i]) for i in range(COLS)])
    try:
        t("write_range_columnar changing one column (100,000 cells)", lambda: eng.write_range_columnar(h, rng, wr2))
    except GridoraEngineError as e:  # the 200,000-cell cap applies until E5b-2
        print(f"  write refused: {e.code}/{e.reason}")
    print(f"max RSS: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")


if __name__ == "__main__":
    main()
