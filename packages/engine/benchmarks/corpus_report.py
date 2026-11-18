"""Per-file table for the test corpus (Review 5): import time, memory, report summary.
Usage: python benchmarks/corpus_report.py
For every readable corpus file: import time, time to parse every row (full materialization),
cells, cells/second. Hostile/unsupported files: outcome and error reason. Single run per file."""
from __future__ import annotations

import gc
import json
import os
import platform
import time
from pathlib import Path

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError

ROOT = Path(__file__).resolve().parents[3] / "corpus"
# Differences between manifest flags and our report that tests prove harmless (see tests/corpus/test_corpus.py)
NOTES = {
    "right-to-left.xlsx": "manifest `drawings` = legacy comment shapes (reported as comments)",
    "DataValidationEvaluations.xlsx": "manifest `drawings` = legacy comment shapes (reported as comments)",
    "FormulaEvalTestData_Copy.xlsx": "manifest `drawings` = legacy comment shapes (reported as comments)",
    "bug62181.xlsx": "manifest `media` = empty directory",
    "LIBRE_OFFICE-116306-0.xlsx": "manifest `names` = auto-filter name only (filter reported)",
}


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return float("nan")


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}\n")
    m = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    files = [ROOT / f["path"] for f in m["files"] if not f["path"].startswith("hostile/")]
    files += sorted(p for p in (ROOT / "private").glob("*") if p.suffix in (".xlsx", ".xls", ".csv"))
    print("| file | size KB | import s | parse-all s | cells | cells/s | RSS after import / parsed MB | report (supported/partial/preserved+unsupported) | note |")
    print("|---|---:|---:|---:|---:|---:|---:|---|---|")
    for p in files:
        eng = create_engine({})
        gc.collect()
        base = rss_mb()
        try:
            t = time.perf_counter()
            if p.suffix == ".csv":
                h, wb = eng.import_csv(p, CsvImportOptions())
                rep = wb.compat
            else:
                h, wb, rep = eng.import_xlsx(p)
            ti = time.perf_counter() - t
            r_import = rss_mb() - base
            st = eng._open[h.id]
            t = time.perf_counter()
            for s in st.sheets:
                if s.lazy is not None:
                    s.lazy.materialize_all()
            tp = time.perf_counter() - t
            cells = st.budget.cells
            rate = f"{cells / tp:,.0f}" if tp > 0.05 else "-"
            r_parsed = rss_mb() - base
            sm = rep.summary if rep else None
            summary = f"{sm.supported}/{sm.partial}/{sm.unsupported}" if sm else "-"
            print(f"| {p.name} | {p.stat().st_size / 1024:,.0f} | {ti:.3f} | {tp:.3f} | {cells:,} | {rate} | {r_import:.0f} / {r_parsed:.0f} | {summary} | {NOTES.get(p.name, '')} |")
            eng.close(h)
        except GridoraEngineError as e:
            print(f"| {p.name} | {p.stat().st_size / 1024:,.0f} | - | - | - | - | - | - | rejected: `{e.reason}` |")
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
