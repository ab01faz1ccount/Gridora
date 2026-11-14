"""Deterministic 100k x 20 XLSX generator for benchmarks (raw XML; not Excel-produced).

Shape: numbers, decimals, shared strings (Persian text), ~3% empty cells, column T is a formula
(A{r}*2+B{r}) with a cached value. 50k unique shared strings. Same fixture for E3/E4 benchmarks.
"""
from __future__ import annotations

import random
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from support import HDR, NS, xlsx_parts

COLS_LETTERS = "ABCDEFGHIJKLMNOPQRST"
NSTR = 50_000


def sheet_xml(rows: int, cols: int, seed: int = 7) -> Iterator[bytes]:
    rnd = random.Random(seed)
    last = COLS_LETTERS[cols - 1]
    yield (HDR + f'<worksheet {NS}><dimension ref="A1:{last}{rows}"/><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetData>').encode()
    for r in range(1, rows + 1):
        p = [f'<row r="{r}" spans="1:{cols}">']
        for c in range(cols):
            ref = f"{COLS_LETTERS[c]}{r}"
            if c == cols - 1:
                p.append(f'<c r="{ref}"><f>A{r}*2+B{r}</f><v>{r * 2.0}</v></c>')
            elif rnd.random() < 0.03:
                continue
            elif c % 5 in (2, 3, 4):
                p.append(f'<c r="{ref}" t="s"><v>{rnd.randint(0, NSTR - 1)}</v></c>')
            else:
                p.append(f'<c r="{ref}"><v>{rnd.random() * 1000:.6f}</v></c>')
        p.append("</row>")
        yield "".join(p).encode()
    yield b"</sheetData></worksheet>"


def build(path: Path, rows: int = 100_000, cols: int = 20) -> Path:
    if path.exists():
        return path
    parts = xlsx_parts(False)
    sst = [f"متن {i} " + "x" * (i % 7) for i in range(NSTR)]
    sst_xml = HDR + f'<sst {NS} count="{NSTR}" uniqueCount="{NSTR}">' + "".join(
        f"<si><t>{s}</t></si>" for s in sst) + "</sst>"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            if name == "xl/worksheets/sheet1.xml":
                with z.open(name, "w", force_zip64=True) as f:
                    for chunk in sheet_xml(rows, cols):
                        f.write(chunk)
            elif name == "xl/sharedStrings.xml":
                z.writestr(name, sst_xml)
            else:
                z.writestr(name, data if isinstance(data, bytes) else data.encode())
    return path
