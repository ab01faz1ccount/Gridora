"""Review 2 / C1.3: replaying deltas on a fresh engine reproduces the live workbook exactly.

Until the snapshot format exists (Phase 4), "a fresh engine loaded with the state at step k" is
modelled by a fresh engine that imports the same source file and replays deltas 1..k. Deltas go
through JSON first, as the API stores them. The fingerprint covers every non-empty cell of every
sheet (value, formula, style id) and never object identity. It can only pass because deltas carry
all changed cells and apply_delta never recalculates (CC-4).
"""
from __future__ import annotations

import hashlib
import random

import pytest
from gridora_contracts.models import (
    BoolValue,
    CellEdit,
    CellPatchDelta,
    ErrValue,
    NumValue,
    StrValue,
    Window,
)
from support import make_xlsx, sheet_doc

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions

WORDS = ["علی", "مریم", "ی", "ک", "text", "", "x" * 40]


def fingerprint(eng, h) -> str:
    state = eng._open[h.id]
    digest = hashlib.sha256()
    for sheet in state.sheets:
        sheet.ensure(0, 1 << 20) if sheet.lazy is None else sheet.lazy.materialize_all()
        rows, cols = sheet.store.used_size()
        for r0 in range(0, rows, 1000):
            for c0 in range(0, cols, 100):
                w = eng.get_cells(h, sheet.id, Window(row0=r0, col0=c0, rows=min(1000, rows - r0), cols=min(100, cols - c0)))
                for c in w.cells:
                    digest.update(f"{sheet.name}|{c.r}|{c.c}|{c.v.model_dump_json() if c.v else ''}|{c.f}|{c.s}\n".encode())
    return digest.hexdigest()


def random_edits(rnd: random.Random, rows: int) -> list[CellEdit]:
    edits = []
    for _ in range(rnd.randint(1, 6)):
        r, c = rnd.randint(0, rows + 20), rnd.choice([0, 1, 2, 3, 5, 8])  # column C holds formulas
        kind = rnd.choice(["num", "str", "bool", "err", "clear"])
        value = {"num": lambda: NumValue(n=rnd.choice([0.0, -1.5, 1e10, rnd.random()])),
                 "str": lambda: StrValue(s=rnd.choice(WORDS)), "bool": lambda: BoolValue(b=rnd.random() < 0.5),
                 "err": lambda: ErrValue(e=rnd.choice(["#N/A", "#DIV/0!", "#SPILL!"])), "clear": lambda: None}[kind]()
        edits.append(CellEdit(r=r, c=c, value=value))
    return edits


def xlsx_source(tmp_path, rows=700):
    body = "".join(
        f'<row r="{r}" spans="1:3"><c r="A{r}"><v>{r}</v></c><c r="B{r}" t="inlineStr"><is><t>t{r}</t></is></c>'
        f'<c r="C{r}"><f>A{r}*2</f><v>{r * 2}</v></c></row>' for r in range(1, rows + 1))
    return make_xlsx(tmp_path / "src.xlsx", sheet_doc(body))


def csv_source(tmp_path, rows=700):
    p = tmp_path / "src.csv"
    p.write_text("a,b,c\n" + "".join(f"{r},w{r},{r * 2}\n" for r in range(rows)), encoding="utf-8")
    return p


def open_source(eng, path):
    if path.suffix == ".xlsx":
        h, _wb, _ = eng.import_xlsx(path)
    else:
        h, _wb = eng.import_csv(path, CsvImportOptions())
    return h, _wb.sheets[0]


@pytest.mark.parametrize("make", [xlsx_source, csv_source])
def test_replay_determinism(tmp_path, make):
    src = make(tmp_path)
    rnd = random.Random(20261114)
    live = create_engine({})
    h, sheet = open_source(live, src)
    fps = [fingerprint(live, h)]
    deltas = []
    for _ in range(40):
        d = live.apply_cell_edits(h, sheet.id, random_edits(rnd, 700))
        deltas.append(CellPatchDelta.model_validate_json(d.model_dump_json()))  # as stored by the API
        fps.append(fingerprint(live, h))
    assert len(set(fps)) > 10  # the edits really changed the workbook

    k = 17
    fresh = create_engine({})
    h2, sheet2 = open_source(fresh, src)
    assert fingerprint(fresh, h2) == fps[0]
    for d in deltas[:k]:
        fresh.apply_delta(h2, d.model_copy(update={"sheet_id": sheet2.id}), inverse=False)
    assert fingerprint(fresh, h2) == fps[k]  # state at step k
    for d in deltas[k:]:
        fresh.apply_delta(h2, d.model_copy(update={"sheet_id": sheet2.id}), inverse=False)
    assert fingerprint(fresh, h2) == fps[-1]  # == the live workbook
    for d in reversed(deltas):  # undo everything
        fresh.apply_delta(h2, d.model_copy(update={"sheet_id": sheet2.id}), inverse=True)
    assert fingerprint(fresh, h2) == fps[0]
    assert all(not s.dirty and not s.orig for s in fresh._open[h2.id].sheets)  # clean: same as the file
    for d in deltas:  # and redo everything
        fresh.apply_delta(h2, d.model_copy(update={"sheet_id": sheet2.id}), inverse=False)
    assert fingerprint(fresh, h2) == fps[-1]
