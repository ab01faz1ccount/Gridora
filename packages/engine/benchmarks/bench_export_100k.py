"""E6 benchmark: export of the 100k x 20 XLSX (lazy reader, row patching).
Usage: python benchmarks/bench_export_100k.py"""
from __future__ import annotations

import os
import platform
import resource
import time
from pathlib import Path

from gridora_contracts.models import CellEdit, NumValue, StrValue
from xlsx_fixture import build

from gridora_engine import create_engine

OUT = Path(__file__).parent / "_out"


def t(label: str, fn):
    t0 = time.perf_counter()
    out = fn()
    print(f"{label:<54}{time.perf_counter() - t0:8.2f} s")
    return out


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    src = build(OUT / "big_100k_x_20.xlsx")
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    sid = wb.sheets[0].id
    out = OUT / "big_export.xlsx"
    t("export, no edits (verbatim copy)", lambda: eng.export_xlsx(h, out))
    eng.apply_cell_edits(h, sid, [CellEdit(r=50_000, c=3, value=NumValue(n=1.5))])
    rep = t("export after 1 edit (1 row rebuilt)", lambda: eng.export_xlsx(h, out))
    print(f"  report items: {[i.code for i in rep.items]}; output {out.stat().st_size / 1e6:.1f} MB")
    batch = [CellEdit(r=r, c=c, value=StrValue(s=f"v{r}-{c}")) for r in range(60_000, 60_500) for c in range(20)]
    eng.apply_cell_edits(h, sid, batch)
    t("export after +10,000 edited cells (500 rows rebuilt)", lambda: eng.export_xlsx(h, out))
    t("re-import of the exported file (lazy)", lambda: create_engine({}).import_xlsx(out))
    print(f"max RSS of the process: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")


if __name__ == "__main__":
    main()
