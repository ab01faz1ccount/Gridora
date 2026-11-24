"""Find (Ctrl+F) and fill (drag handle, Ctrl+D / Ctrl+R) in the engine."""
from __future__ import annotations

import pytest
from gridora_contracts.models import CellEdit, NumValue, StrValue, Window
from support import make_xlsx, sheet_doc

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError


def book(tmp_path, rows):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows, "")))
    return eng, h, wb.sheets[0]


def put(eng, h, s, r, c, v):
    value = NumValue(n=v) if isinstance(v, (int, float)) else StrValue(s=v)
    eng.apply_cell_edits(h, s.id, [CellEdit(r=r, c=c, value=value)])


def grid(eng, h, s, rows, cols):
    w = eng.get_cells(h, s.id, Window(row0=0, col0=0, rows=rows, cols=cols))
    return {(c.r, c.c): (c.v.n if c.v and c.v.k == "num" else getattr(c.v, "s", None)) for c in w.cells if c.v}


def fill(eng, h, s, source, target):
    eng.apply_cell_edits(h, s.id, eng.fill_edits(h, s.id, source, target))


def test_find_folds_persian_digits_letters_and_case(tmp_path):
    eng, h, s = book(tmp_path, "")
    put(eng, h, s, 0, 0, "Total ۱۲۳")
    put(eng, h, s, 3, 2, "كتاب")  # Arabic kaf
    put(eng, h, s, 5, 1, 123)
    assert eng.find_cells(h, s.id, "total 123") == ([(0, 0)], False)  # case + Persian digits
    assert eng.find_cells(h, s.id, "123") == ([(0, 0), (5, 1)], False)  # row-major order
    assert eng.find_cells(h, s.id, "کتاب") == ([(3, 2)], False)  # Persian kaf finds Arabic kaf
    assert eng.find_cells(h, s.id, "TOTAL", match_case=True) == ([], False)
    assert eng.find_cells(h, s.id, "123", whole_cell=True) == ([(5, 1)], False)


def test_find_in_formulas_continues_after_a_cell_and_limits(tmp_path):
    rows = '<row r="1"><c r="A1"><v>1</v></c><c r="B1"><f>A1*2</f><v>2</v></c></row>'
    eng, h, s = book(tmp_path, rows)
    assert eng.find_cells(h, s.id, "A1*") == ([], False)  # formula text is not searched by default
    assert eng.find_cells(h, s.id, "A1*", in_formulas=True) == ([(0, 1)], False)
    for r in range(1, 6):
        put(eng, h, s, r, 0, "x")
    found, more = eng.find_cells(h, s.id, "x", limit=2)
    assert found == [(1, 0), (2, 0)] and more
    assert eng.find_cells(h, s.id, "x", after=(2, 0), limit=10) == ([(3, 0), (4, 0), (5, 0)], False)


def test_fill_down_continues_a_line_and_translates_formulas(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c><c r="B1"><f>A1*2</f><v>2</v></c></row>'
            '<row r="2"><c r="A2"><v>3</v></c><c r="B2"><f>A2*2</f><v>6</v></c></row>')
    eng, h, s = book(tmp_path, rows)
    fill(eng, h, s, (0, 0, 1, 1), (2, 0, 4, 1))
    g = grid(eng, h, s, 5, 2)
    assert [g[(r, 0)] for r in range(5)] == [1, 3, 5, 7, 9]
    assert [g[(r, 1)] for r in range(5)] == [2, 6, 10, 14, 18]  # B3 = A3*2 ...


def test_fill_one_number_repeats_and_text_series_counts_up(tmp_path):
    eng, h, s = book(tmp_path, "")
    put(eng, h, s, 0, 0, 7)
    put(eng, h, s, 0, 1, "Item 9")
    put(eng, h, s, 0, 2, "Mon")
    fill(eng, h, s, (0, 0, 0, 2), (1, 0, 2, 2))
    g = grid(eng, h, s, 3, 3)
    assert [g[(r, 0)] for r in range(3)] == [7, 7, 7]
    assert [g[(r, 1)] for r in range(3)] == ["Item 9", "Item 10", "Item 11"]
    assert [g[(r, 2)] for r in range(3)] == ["Mon", "Mon", "Mon"]


def test_fill_up_left_and_right_and_pattern_repeat(tmp_path):
    eng, h, s = book(tmp_path, "")
    put(eng, h, s, 5, 5, 10)
    put(eng, h, s, 6, 5, 20)
    fill(eng, h, s, (5, 5, 6, 5), (2, 5, 4, 5))  # up: ... 4 ... continues the line backwards
    g = grid(eng, h, s, 7, 6)
    assert g[(4, 5)] == 0 and g[(3, 5)] == -10 and g[(2, 5)] == -20
    put(eng, h, s, 0, 0, "a")
    put(eng, h, s, 0, 1, "b")
    fill(eng, h, s, (0, 0, 0, 1), (0, 2, 0, 5))  # right: a b a b a b
    g = grid(eng, h, s, 1, 6)
    assert [g[(0, c)] for c in range(6)] == ["a", "b", "a", "b", "a", "b"]


def test_fill_is_one_undo_step_and_rejects_bad_shapes(tmp_path):
    eng, h, s = book(tmp_path, "")
    put(eng, h, s, 0, 0, 1)
    d = eng.apply_cell_edits(h, s.id, eng.fill_edits(h, s.id, (0, 0, 0, 0), (1, 0, 3, 0)))
    assert len(grid(eng, h, s, 5, 1)) == 4
    eng.apply_delta(h, d, inverse=True)
    assert len(grid(eng, h, s, 5, 1)) == 1
    with pytest.raises(GridoraEngineError):
        eng.fill_edits(h, s.id, (0, 0, 0, 0), (2, 1, 3, 1))  # not against the source's side
    with pytest.raises(GridoraEngineError):
        eng.fill_edits(h, s.id, (0, 0, 0, 0), (1, 0, 60_000, 0))  # too large
