"""E5b-2 benchmark: range snapshot deltas on the 100k x 20 XLSX (1.94 M cells).
Usage: python benchmarks/bench_snapshot_100k.py"""
from __future__ import annotations

import hashlib
import os
import platform
import resource
import time
from pathlib import Path

from gridora_contracts.models import ColumnarColumn, ColumnarRange, Range
from xlsx_fixture import build

from gridora_engine import create_engine

OUT = Path(__file__).parent / "_out"
ROWS, COLS = 100_000, 20


class Blobs:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        ref = hashlib.sha256(data).hexdigest()[:16]
        self.data[ref] = data
        return ref

    def get(self, ref: str) -> bytes:
        return self.data[ref]


def t(label: str, fn):
    t0 = time.perf_counter()
    out = fn()
    print(f"{label:<60}{time.perf_counter() - t0:8.2f} s")
    return out


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    blobs = Blobs()
    eng = create_engine({}, blobs)
    h, wb, _ = eng.import_xlsx(build(OUT / "big_100k_x_20.xlsx"))
    sid = wb.sheets[0].id
    rng = Range(sheet_id=sid, r0=0, c0=0, r1=ROWS - 1, c1=COLS - 2)  # without the formula column T
    cur = t("read_range_columnar (parses the sheet first)", lambda: eng.read_range_columnar(h, rng))
    new_cols = []
    for c in cur.columns:
        if c.kind == "num":
            new_cols.append(ColumnarColumn(kind="num", values=[None if v is None else v + 1.0 for v in c.values]))
        else:
            new_cols.append(ColumnarColumn(kind=c.kind, values=list(c.values)))
    data = ColumnarRange(range=rng, columns=new_cols)
    d = t("write_range_columnar -> range_snapshot (1.8 M cells)", lambda: eng.write_range_columnar(h, rng, data))
    sizes = [len(v) for v in blobs.data.values()]
    print(f"  delta kind: {d.kind}; cell_count={d.cell_count:,}; blobs: {[f'{s / 1e6:.1f} MB' for s in sizes]}; delta JSON {len(d.model_dump_json())} bytes")
    t("undo (apply_delta inverse)", lambda: eng.apply_delta(h, d, inverse=True))
    t("redo (apply_delta)", lambda: eng.apply_delta(h, d, inverse=False))
    out = OUT / "snap_export.xlsx"
    t("export after the bulk write (regenerates 100,000 rows)", lambda: eng.export_xlsx(h, out))
    print(f"  output {out.stat().st_size / 1e6:.1f} MB; max RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")


if __name__ == "__main__":
    main()
