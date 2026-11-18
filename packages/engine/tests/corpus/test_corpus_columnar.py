"""ColumnarEngine equivalence on real files: read_range_columnar must agree with get_cells,
cell by cell, for every sheet of every readable corpus file (first 5000 rows of each sheet)."""
from __future__ import annotations

from pathlib import Path

import pytest
from corpus_data import MANIFEST, ROOT, find_private
from gridora_contracts.models import Range, Window

from gridora_engine import create_engine

POI = [f["path"] for f in MANIFEST["files"] if f["path"].startswith("apache-poi/")]
PRIVATE = [f for f in MANIFEST.get("private", []) if f["path"].endswith(".xlsx")]
KIND = {"num": ("num", "n"), "str": ("str", "s"), "bool": ("bool", "b"), "date": ("date", "iso")}


def check(path: Path) -> int:
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(path)
    compared = 0
    has_formula_columns = 0
    for s in wb.sheets:
        rows, cols = min(s.row_count, 5000), min(s.col_count, 100)
        if not rows or not cols:
            continue
        col = eng.read_range_columnar(h, Range(sheet_id=s.id, r0=0, c0=0, r1=rows - 1, c1=cols - 1))
        cells: dict[tuple[int, int], object] = {}
        for r0 in range(0, rows, 1000):
            w = eng.get_cells(h, s.id, Window(row0=r0, col0=0, rows=min(1000, rows - r0), cols=cols))
            cells.update({(c.r, c.c): c for c in w.cells})
        formulas = False
        for ci, column in enumerate(col.columns):
            for ri, got in enumerate(column.values):
                cell = cells.get((ri, ci))
                if got is None:
                    exp_none = cell is None or cell.v is None
                    assert exp_none, (path.name, s.name, ri, ci)
                else:
                    exp = cell.v.model_dump()
                    val = got if column.kind == "mixed" else {"k": KIND[column.kind][0], KIND[column.kind][1]: got}
                    assert val == exp, (path.name, s.name, ri, ci, val, exp)
                    compared += 1
        formulas = any(c.f for c in cells.values())
        assert col.has_formulas or not formulas, (path.name, s.name)  # a formula cell must set the flag
        has_formula_columns += col.has_formulas
    return compared


@pytest.mark.parametrize("rel", POI, ids=[Path(p).name for p in POI])
def test_columnar_read_equals_get_cells_on_apache_poi_file(corpus_root, rel):
    check(ROOT / rel)


@pytest.mark.parametrize("entry", PRIVATE, ids=[Path(f["path"]).name[:40] for f in PRIVATE])
def test_columnar_read_equals_get_cells_on_private_file(corpus_root, entry):
    p = find_private(entry)
    if p is None:
        pytest.skip("private file not present")
    assert check(p) > 0
