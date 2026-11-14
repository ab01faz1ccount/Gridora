from __future__ import annotations

from pathlib import Path

import pytest
from gridora_contracts.models import Window

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions


@pytest.fixture
def engine():
    return create_engine({})


@pytest.fixture
def load(engine, tmp_path):
    """load(bytes, **opts) -> (handle, workbook); uses the real file path API."""

    def _load(data: bytes, **opts):
        p: Path = tmp_path / "in.csv"
        p.write_bytes(data)
        return engine.import_csv(p, CsvImportOptions(**opts))

    return _load


def cells_of(engine, h, wb, rows=1000, cols=100):
    sid = wb.sheets[0].id
    win = engine.get_cells(h, sid, Window(row0=0, col0=0, rows=rows, cols=cols))
    out = {}
    for c in win.cells:
        v = c.v
        out[(c.r, c.c)] = (
            v.n if v.k == "num" else v.s if v.k == "str" else v.b if v.k == "bool" else v.e
        )
    return out
