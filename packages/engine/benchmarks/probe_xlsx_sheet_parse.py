"""PROBE (not the XLSX reader): lower bound for streaming-parsing a 100k x 20 worksheet XML.

Generates worksheet XML in Excel's usual shape (rows with r/spans, cells with r, t, s, <v>) and
parses it with xml.parsers.expat into the real SheetStore. Missing on purpose: shared-string
table parsing, styles, formulas (<f>), row byte-offset indexing, feature detection, limits
checks and error handling. The real reader (E4) will be slower than this probe.
"""
from __future__ import annotations

import random
import time
import tracemalloc
from pathlib import Path
from xml.parsers import expat

from gridora_engine.model.sheet import SheetStore, StoreBudget
from gridora_engine.model.values import NUM, STR

OUT = Path(__file__).parent / "_out"
ROWS, COLS = 100_000, 20
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def build(path: Path) -> None:
    rnd = random.Random(7)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<dimension ref="A1:{LETTERS[COLS - 1]}{ROWS}"/><sheetData>')
        for r in range(1, ROWS + 1):
            parts = [f'<row r="{r}" spans="1:{COLS}">']
            for c in range(COLS):
                ref = f"{LETTERS[c]}{r}"
                if rnd.random() < 0.03:
                    continue
                if c % 5 in (2, 3, 4):
                    parts.append(f'<c r="{ref}" t="s"><v>{rnd.randint(0, 390_000)}</v></c>')
                else:
                    parts.append(f'<c r="{ref}" s="1"><v>{rnd.random() * 1000:.6f}</v></c>')
            parts.append("</row>")
            f.write("".join(parts))
        f.write("</sheetData></worksheet>")


def col_index(ref: str) -> tuple[int, int]:
    i = 0
    n = 0
    while ref[i].isalpha():
        n = n * 26 + ord(ref[i]) - 64
        i += 1
    return int(ref[i:]) - 1, n - 1


def parse(path: Path) -> SheetStore:
    store = SheetStore(StoreBudget(2 * 1024**3, 5_000_000))
    put = store.put
    state = {"r": 0, "c": 0, "t": "", "in_v": False, "buf": []}

    def start(name: str, attrs: dict[str, str]) -> None:
        if name == "c":
            state["r"], state["c"] = col_index(attrs["r"])
            state["t"] = attrs.get("t", "")
        elif name == "v":
            state["in_v"] = True
            state["buf"] = []

    def end(name: str) -> None:
        if name == "v":
            state["in_v"] = False
            txt = "".join(state["buf"])  # type: ignore[arg-type]
            if state["t"] == "s":
                put(state["r"], state["c"], STR, float(int(txt)))  # type: ignore[arg-type]
            else:
                put(state["r"], state["c"], NUM, float(txt))  # type: ignore[arg-type]

    def chars(data: str) -> None:
        if state["in_v"]:
            state["buf"].append(data)  # type: ignore[union-attr]

    p = expat.ParserCreate()
    p.buffer_text = True
    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = start, end, chars
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            p.Parse(chunk, False)
    p.Parse(b"", True)
    return store


def main() -> None:
    OUT.mkdir(exist_ok=True)
    p = OUT / "probe_sheet.xml"
    if not p.exists():
        build(p)
    print(f"sheet xml: {p.stat().st_size / 1e6:.1f} MB (uncompressed)")
    t = time.perf_counter()
    store = parse(p)
    print(f"expat stream parse into SheetStore: {time.perf_counter() - t:.2f} s, "
          f"cells={store._budget.cells}")
    del store
    tracemalloc.start()
    store = parse(p)
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"tracemalloc current/peak: {cur / 1e6:.1f} / {peak / 1e6:.1f} MB")
    t = time.perf_counter()
    q = expat.ParserCreate()
    q.Parse(p.read_bytes(), True)
    print(f"expat with no handlers (floor):      {time.perf_counter() - t:.2f} s")
    del store


if __name__ == "__main__":
    main()
