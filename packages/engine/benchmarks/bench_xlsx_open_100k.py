"""E4 benchmark (Review 2 order): open speed and memory of a 100k x 20 XLSX with the lazy reader.

Usage: python benchmarks/bench_xlsx_open_100k.py
Measures import_xlsx (package validation, workbook/styles/shared strings, sheet spool + row index,
report), first-viewport reads at the top/middle/bottom, the contract-max window, then the cost of
reading every row (full materialization) and of the eager fallback path for comparison.
Memory: RSS from /proc (growth since process start of each phase) and the temp spool size.
"""
from __future__ import annotations

import gc
import os
import platform
import time
from pathlib import Path

from gridora_contracts.models import Window
from xlsx_fixture import build

from gridora_engine import create_engine

OUT = Path(__file__).parent / "_out"


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return float("nan")


def t(label: str, fn, rss_before: float | None = None):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    extra = f"   RSS +{rss_mb() - rss_before:6.0f} MB" if rss_before is not None else ""
    print(f"{label:<44}{dt:8.3f} s{extra}")
    return out


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    src = build(OUT / "big_100k_x_20.xlsx")
    print(f"file: {src.stat().st_size / 1e6:.1f} MB (zip), 100000 rows x 20 cols, 50k shared strings")
    eng = create_engine({})
    gc.collect()
    base = rss_mb()
    h, wb, rep = t("import_xlsx (lazy)", lambda: eng.import_xlsx(src), base)
    st = eng._open[h.id]
    sheet = st.sheets[0]
    print(f"  sheet meta rows x cols (hints): {wb.sheets[0].row_count} x {wb.sheets[0].col_count};"
          f" spool {sheet.lazy.source.size / 1e6:.1f} MB; report items: {len(rep.items)}")
    sid = wb.sheets[0].id
    for r0, label in ((0, "top"), (50_000, "middle"), (99_900, "bottom")):
        t(f"first read 100x20 at {label} (cold block)",
          lambda r0=r0: eng.get_cells(h, sid, Window(row0=r0, col0=0, rows=100, cols=20)), rss_before=base)
    t("contract-max window 1000x100 (rows 20000+)",
      lambda: eng.get_cells(h, sid, Window(row0=20_000, col0=0, rows=1000, cols=100)), rss_before=base)
    t("warm re-read 100x20 (already parsed)",
      lambda: eng.get_cells(h, sid, Window(row0=0, col0=0, rows=100, cols=20)))

    def read_all() -> None:
        for r0 in range(0, 100_000, 1000):
            eng.get_cells(h, sid, Window(row0=r0, col0=0, rows=1000, cols=20))

    t("read every row (full materialization)", read_all, rss_before=base)
    print(f"  cells in store: {st.budget.cells}; chunk bytes {st.budget.bytes_used / 1e6:.0f} MB;"
          f" strings interned {len(st.strings)}; blocks parsed {len(sheet.lazy.parsed_blocks)}")
    eng.close(h)
    del h, wb, rep, st, sheet
    gc.collect()

    base2 = rss_mb()
    h, _wb, _ = eng.import_xlsx(src)
    sheet = eng._open[h.id].sheets[0]
    t("eager: materialize_all() on a fresh import", sheet.lazy.materialize_all, base2)
    eng.close(h)


if __name__ == "__main__":
    main()
