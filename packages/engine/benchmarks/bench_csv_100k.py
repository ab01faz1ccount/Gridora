"""E1 benchmark (Phase 2 review C1.1): CSV import / get_cells / export at 100k rows x 20 cols.

Usage: python benchmarks/bench_csv_100k.py [rows] [cols]
Generates a deterministic file (numbers, Persian text, identifiers with leading zeros, Persian
digits, empty cells) under benchmarks/_out/, then measures wall time and memory. Memory:
tracemalloc peak is measured in a SEPARATE pass (it slows execution), RSS is read from
/proc/self/status. Results are only meaningful with the printed hardware/version header.
"""
from __future__ import annotations

import gc
import os
import platform
import random
import sys
import time
import tracemalloc
from pathlib import Path

from gridora_contracts.models import Window

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions

OUT = Path(__file__).parent / "_out"
WORDS = ["علی", "مریم", "تهران", "شیراز", "فروش", "مرجوعی", "الف", "ب", "پ", "گزارش", "ok", "N/A"]


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return float("nan")


def make_file(rows: int, cols: int) -> Path:
    OUT.mkdir(exist_ok=True)
    p = OUT / f"bench_{rows}x{cols}.csv"
    if p.exists():
        return p
    rnd = random.Random(1234)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(f"col{c}" for c in range(cols)) + "\n")
        for r in range(rows):
            row = []
            for c in range(cols):
                k = c % 5
                if rnd.random() < 0.03:
                    row.append("")
                elif k == 0:
                    row.append(str(rnd.randint(0, 10**6)))
                elif k == 1:
                    row.append(f"{rnd.random() * 1000:.4f}")
                elif k == 2:
                    row.append(rnd.choice(WORDS) + f" {rnd.randint(0, 500)}")
                elif k == 3:
                    row.append("09" + str(rnd.randint(10**8, 10**9 - 1)))
                else:
                    row.append("".join(chr(0x06F0 + int(d)) for d in str(rnd.randint(1, 99999))))
            f.write(",".join(row) + "\n")
    return p


def timed(label: str, fn):
    t = time.perf_counter()
    out = fn()
    print(f"{label:<34}{time.perf_counter() - t:9.3f} s")
    return out


def main() -> None:
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    p = make_file(rows, cols)
    print(f"file: {rows}x{cols}, {p.stat().st_size / 1e6:.1f} MB")
    eng = create_engine({})
    opts = CsvImportOptions()

    gc.collect()
    base = rss_mb()
    h, wb = timed("import_csv", lambda: eng.import_csv(p, opts))
    print(f"RSS growth after import           {rss_mb() - base:9.1f} MB")
    sid = wb.sheets[0].id
    st = eng._open[h.id]
    print(f"cells={st.budget.cells} chunks_bytes={st.budget.bytes_used / 1e6:.1f} MB "
          f"strings={len(st.strings)}")
    for r0, label in ((0, "top"), (rows // 2, "middle"), (max(rows - 100, 0), "bottom")):
        timed(f"get_cells 100x20 {label}",
              lambda r0=r0: eng.get_cells(h, sid, Window(row0=r0, col0=0, rows=100, cols=20)))
    timed("get_cells 1000x100 (contract max)",
          lambda: eng.get_cells(h, sid, Window(row0=0, col0=0, rows=1000, cols=100)))
    out = OUT / "export.csv"
    timed("export_csv", lambda: eng.export_csv(h, sid, out))
    print(f"export size                       {out.stat().st_size / 1e6:9.1f} MB")
    eng.close(h)
    del h, wb, st

    # Separate pass: tracemalloc peak (Python-level allocations), slows the import down.
    gc.collect()
    tracemalloc.start()
    h, _wb = eng.import_csv(p, opts)
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"tracemalloc current/peak          {cur / 1e6:9.1f} / {peak / 1e6:.1f} MB")
    eng.close(h)


if __name__ == "__main__":
    main()
