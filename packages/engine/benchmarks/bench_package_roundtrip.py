"""E3 benchmark: open (validate) and no-op write of the 100k x 20 XLSX.
Usage: python benchmarks/bench_package_roundtrip.py"""
from __future__ import annotations

import hashlib
import os
import platform
import resource
import time
import zipfile
from pathlib import Path

from xlsx_fixture import build

from gridora_engine.limits import ResourceLimits
from gridora_engine.package.parts import PackageModel
from gridora_engine.package.zipout import write_package

OUT = Path(__file__).parent / "_out"


def digests(p: Path) -> dict[str, str]:
    with zipfile.ZipFile(p) as z:
        return {i.filename: hashlib.sha256(z.read(i)).hexdigest() for i in z.infolist()}


def main() -> None:
    print(f"python {platform.python_version()} {platform.platform()} cpus={os.cpu_count()}")
    src = build(OUT / "big_100k_x_20.xlsx")
    out = OUT / "big_roundtrip.xlsx"
    print(f"file: {src.stat().st_size / 1e6:.1f} MB")
    t = time.perf_counter()
    m = PackageModel.open(src, ResourceLimits())
    print(f"open + validate structure   {time.perf_counter() - t:7.3f} s")
    t = time.perf_counter()
    write_package(m, out)
    print(f"no-op write                 {time.perf_counter() - t:7.2f} s")
    m.close()
    print(f"max RSS                     {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:7.0f} MB")
    print("all parts byte-equal:", digests(src) == digests(out))


if __name__ == "__main__":
    main()
