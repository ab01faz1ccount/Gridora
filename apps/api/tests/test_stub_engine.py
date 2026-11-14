from __future__ import annotations

from pathlib import Path

import pytest
from gridora_contracts.models import (
    CellEdit,
    CellPatchDelta,
    NumValue,
    StrValue,
    Window,
)
from gridora_contracts.protocols import FormattingEngine, StructureEngine, WorkbookEngine

from gridora_api.composition.stubs.engine_stub import StubEngine, StubHandle
from gridora_api.core.errors import DomainError

from .stubkit import Opts, open_csv


def win(h: StubHandle, r: int = 0, c: int = 0, rows: int = 50, cols: int = 20) -> Window:
    return Window(row0=r, col0=c, rows=rows, cols=cols)


def snapshot(eng: StubEngine, h: StubHandle) -> list[tuple[int, int, object]]:
    cw = eng.get_cells(h, h.sheet_id, win(h))
    return [(c.r, c.c, c.v.model_dump() if c.v else None) for c in cw.cells]


def test_satisfies_the_engine_protocol_and_no_optional_extensions() -> None:
    e = StubEngine()
    assert isinstance(e, WorkbookEngine)
    assert not isinstance(e, FormattingEngine) and not isinstance(e, StructureEngine)


def test_csv_import_types_and_report(tmp_path: Path) -> None:
    eng, h, wb = open_csv(tmp_path, b"name,qty\nali,3\nreza,4.5\n")
    assert [s.row_count for s in wb.sheets] == [3] and wb.sheets[0].col_count == 2
    cells = {(c.r, c.c): c.v for c in eng.get_cells(h, h.sheet_id, win(h)).cells}
    assert cells[(1, 0)] == StrValue(s="ali") and cells[(1, 1)] == NumValue(n=3.0)
    assert wb.compat is not None and wb.compat.items[0].code == "stub.engine"
    assert wb.compat.summary.partial == 1  # never claims full support


def test_formula_looking_text_stays_text(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n=SUM(1+1)\n@cmd\n")
    cells = {(c.r, c.c): c for c in eng.get_cells(h, h.sheet_id, win(h)).cells}
    assert cells[(1, 0)].v == StrValue(s="=SUM(1+1)") and cells[(1, 0)].f is None


def test_persian_utf8_bom_and_windows_1256(tmp_path: Path) -> None:
    # cp1256 has Arabic yeh (U+064A) but not Persian yeh (U+06CC): use text both can carry.
    text = "نام,شهر\nعلي,تهران\n"
    for raw in (b"\xef\xbb\xbf" + text.encode("utf-8"), text.encode("cp1256")):
        eng, h, _ = open_csv(tmp_path, raw)
        cells = eng.get_cells(h, h.sheet_id, win(h)).cells
        vals = [c.v.s for c in cells if isinstance(c.v, StrValue)]
        assert vals == ["نام", "شهر", "علي", "تهران"]


@pytest.mark.parametrize("delim", [";", "\t", "|"])
def test_delimiter_detection(tmp_path: Path, delim: str) -> None:
    eng, h, wb = open_csv(tmp_path, f"a{delim}b{delim}c\n1{delim}2{delim}3\n".encode())
    assert wb.sheets[0].col_count == 3


def test_xlsx_is_refused_with_a_clear_stub_error(tmp_path: Path) -> None:
    with pytest.raises(DomainError) as ei:
        StubEngine().import_xlsx(tmp_path / "x.xlsx")
    assert ei.value.code == "unsupported_workbook"
    assert ei.value.details[0].code == "stub.xlsx_unsupported"


def test_window_clips_and_returns_non_empty_only(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a,,c\n,,\n1,2,3\n")
    cw = eng.get_cells(h, h.sheet_id, Window(row0=2, col0=1, rows=5, cols=5))
    assert [(c.r, c.c) for c in cw.cells] == [(2, 1), (2, 2)]
    assert (cw.row0, cw.col0, cw.rows, cw.cols) == (2, 1, 5, 5)


def test_edit_returns_delta_with_before_and_after(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a,b\n1,2\n")
    d = eng.apply_cell_edits(
        h,
        h.sheet_id,
        [CellEdit(r=1, c=0, value=NumValue(n=9)), CellEdit(r=5, c=5, value=StrValue(s="new"))],
    )
    assert isinstance(d, CellPatchDelta)
    assert d.before[0].v == NumValue(n=1.0) and d.after[0].v == NumValue(n=9)
    assert d.before[1].v is None and d.after[1].v == StrValue(s="new")  # was empty


def test_clearing_a_cell(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n1\n")
    eng.apply_cell_edits(h, h.sheet_id, [CellEdit(r=1, c=0)])
    assert (1, 0) not in {(c.r, c.c) for c in eng.get_cells(h, h.sheet_id, win(h)).cells}


def test_formula_edit_is_rejected_with_pointer(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n1\n")
    with pytest.raises(DomainError) as ei:
        eng.apply_cell_edits(
            h,
            h.sheet_id,
            [CellEdit(r=0, c=0, value=StrValue(s="x")), CellEdit(r=1, c=0, formula="=1+1")],
        )
    assert ei.value.code == "validation_failed" and ei.value.details[0].path == "/edits/1/formula"
    assert snapshot(eng, h)[0][2] == StrValue(s="a").model_dump()  # nothing was applied


def test_undo_redo_replay_is_exact(tmp_path: Path) -> None:
    """Replay-equals-live (C1.3 on my side): delta forward/inverse restores exact state."""
    eng, h, _ = open_csv(tmp_path, b"a,b\n1,2\n3,4\n", file_id="f1")
    start = snapshot(eng, h)
    d = eng.apply_cell_edits(
        h,
        h.sheet_id,
        [
            CellEdit(r=1, c=0, value=NumValue(n=100)),
            CellEdit(r=9, c=9, value=StrValue(s="z")),
            CellEdit(r=2, c=1),
        ],
    )
    live = snapshot(eng, h)
    eng.apply_delta(h, d, inverse=True)
    assert snapshot(eng, h) == start
    eng.apply_delta(h, d, inverse=False)
    assert snapshot(eng, h) == live
    # and a fresh copy rebuilt from the file + replayed delta equals the live state
    eng2, h2, _ = open_csv(tmp_path, b"a,b\n1,2\n3,4\n", file_id="f1")
    eng2.apply_delta(h2, d, inverse=False)
    assert snapshot(eng2, h2) == live


def test_closed_or_foreign_handles_and_unknown_sheets(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n1\n")
    with pytest.raises(DomainError) as e1:
        eng.get_cells(h, "nope", win(h))
    assert e1.value.code == "not_found"
    eng.close(h)
    with pytest.raises(DomainError) as e2:
        eng.get_cells(h, h.sheet_id, win(h))
    assert e2.value.code == "not_found"
    with pytest.raises(DomainError):
        eng.get_cells(object(), "x", win(h))  # type: ignore[arg-type]


def test_export_csv_roundtrip_with_persian(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, "نام,عدد\nعلی,2\n".encode())
    out = tmp_path / "out.csv"
    eng.export_csv(h, h.sheet_id, out)
    eng2, h2, _ = open_csv(tmp_path, out.read_bytes())
    assert snapshot(eng2, h2) == snapshot(eng, h)
    with pytest.raises(DomainError) as ei:
        eng.export_xlsx(h, tmp_path / "o.xlsx")
    assert ei.value.code == "unsupported_workbook"


def test_oversized_sheet_is_refused(tmp_path: Path) -> None:
    p = tmp_path / "big.csv"
    p.write_text("a,b\n" + "1,2\n" * 10)
    with pytest.raises(DomainError) as ei:
        StubEngine(max_cells=5).import_csv(p, Opts())  # type: ignore[arg-type]
    assert ei.value.code == "import_failed"


def test_import_keeps_file_id(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n")
    _, wb = StubEngine().import_csv(p, Opts(), file_id="f-123")  # type: ignore[arg-type]
    assert wb.file_id == "f-123"
