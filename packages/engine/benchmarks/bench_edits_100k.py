"""E5 benchmark: edit and undo latency on the 100k x 20 XLSX (lazy reader).
Usage: python benchmarks/bench_edits_100k.py"""
from __future__ import annotations

import os
import platform
import time
from pathlib import Path

from gridora_contracts.models import CellEdit, NumValue, StrValue, Window
from xlsx_fixture import build

from gridora_engine import create_engine

OUT = Path(__file__).parent / "_out"


def t(label: str, fn):
    t0 = time.perf_counter()
    out = fn()
    print(f"{label:<52}{(time.perf_counter() - t0) * 1000:10.1f} ms")
    return out


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(build(OUT / "big_100k_x_20.xlsx"))
    sid = wb.sheets[0].id
    one = [CellEdit(r=50_000, c=3, value=NumValue(n=1.5))]
    d1 = t("1 edit in a cold block (loads the block first)", lambda: eng.apply_cell_edits(h, sid, one))
    t("1 edit in the same (now warm) block", lambda: eng.apply_cell_edits(h, sid, [CellEdit(r=50_001, c=3, value=NumValue(n=2.5))]))
    t("undo of the first edit (apply_delta inverse)", lambda: eng.apply_delta(h, d1, inverse=True))
    batch = [CellEdit(r=r, c=c, value=StrValue(s=f"v{r}-{c}")) for r in range(60_000, 60_500) for c in range(20)]
    d = t("10,000-cell edit (500 rows x 20 cols, cold blocks)", lambda: eng.apply_cell_edits(h, sid, batch))
    t("undo of the 10,000-cell edit", lambda: eng.apply_delta(h, d, inverse=True))
    t("redo of the 10,000-cell edit", lambda: eng.apply_delta(h, d, inverse=False))
    js = t("delta -> JSON (10,000 cells before+after)", lambda: d.model_dump_json())
    print(f"  delta JSON size: {len(js) / 1e6:.1f} MB for {len(d.after)} cells")
    t("read back the edited window (1000x20)", lambda: eng.get_cells(h, sid, Window(row0=60_000, col0=0, rows=1000, cols=20)))
    sh = eng._open[h.id].sheets[0]
    print(f"dirty cells now: {len(sh.dirty)}")
    eng.close(h)


if __name__ == "__main__":
    main()
