"""Open-time table for the test corpus (Agent 0 order). Usage: python benchmarks/corpus_report.py
For every readable corpus file: import time, time to parse every row (full materialization),
cells, cells/second. Hostile/unsupported files: outcome and error reason. Single run per file."""
from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError

ROOT = Path(__file__).resolve().parents[3] / "corpus"


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}\n")
    m = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    files = [ROOT / f["path"] for f in m["files"] if not f["path"].startswith("hostile/")]
    files += sorted(p for p in (ROOT / "private").glob("*") if p.suffix in (".xlsx", ".xls", ".csv"))
    print("| file | size KB | import s | parse-all s | cells | cells/s | report items | note |")
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    for p in files:
        eng = create_engine({})
        try:
            t = time.perf_counter()
            if p.suffix == ".csv":
                h, wb = eng.import_csv(p, CsvImportOptions())
                items = len(wb.compat.items) if wb.compat else 0
            else:
                h, wb, rep = eng.import_xlsx(p)
                items = len(rep.items)
            ti = time.perf_counter() - t
            st = eng._open[h.id]
            t = time.perf_counter()
            for s in st.sheets:
                if s.lazy is not None:
                    s.lazy.materialize_all()
            tp = time.perf_counter() - t
            cells = st.budget.cells
            rate = f"{cells / tp:,.0f}" if tp > 0.05 else "-"
            print(f"| {p.name} | {p.stat().st_size / 1024:,.0f} | {ti:.3f} | {tp:.3f} | {cells:,} | {rate} | {items} | |")
            eng.close(h)
        except GridoraEngineError as e:
            print(f"| {p.name} | {p.stat().st_size / 1024:,.0f} | - | - | - | - | - | `{e.reason}` |")
    print("\nHostile files:\n\n| file | outcome |\n|---|---|")
    for f in m["files"]:
        if not f["path"].startswith("hostile/"):
            continue
        p = ROOT / f["path"]
        t = time.perf_counter()
        try:
            h, _wb, _rep = create_engine({}).import_xlsx(p)
            res = "imported"
        except GridoraEngineError as e:
            res = f"`{e.code}` / `{e.reason}`"
        print(f"| {p.name[:60]} | {res} ({time.perf_counter() - t:.3f} s) |")


if __name__ == "__main__":
    main()
