"""Formula engine integrated with edit / undo / redo (E7)."""
from __future__ import annotations

from gridora_contracts.models import CellEdit, NumValue, Window
from support import make_xlsx, sheet_doc

from gridora_engine import create_engine


def fx(r, c, f):
    return CellEdit(r=r, c=c, formula=f)


def nm(r, c, n):
    return CellEdit(r=r, c=c, value=NumValue(n=n))


def cell(eng, h, s, r, c):
    w = eng.get_cells(h, s.id, Window(row0=r, col0=c, rows=1, cols=1))
    return w.cells[0] if w.cells else None


def val(eng, h, s, r, c):
    x = cell(eng, h, s, r, c)
    return None if x is None or x.v is None else (x.v.n if x.v.k == "num" else getattr(x.v, "s", None) or getattr(x.v, "code", None) or x.v.k)


def book(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>2</v></c><c r="B1"><f>A1*10</f><v>20</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows, "")))
    return eng, h, wb.sheets[0]


def test_edit_recalculates_dependents_and_undo_redo_restore(tmp_path):
    eng, h, s = book(tmp_path)
    d = eng.apply_cell_edits(h, s.id, [nm(0, 0, 5)])
    assert val(eng, h, s, 0, 1) == 50.0
    assert any(c.r == 0 and c.c == 1 and c.v.n == 50.0 for c in d.after)  # dependent is in the delta
    eng.apply_delta(h, d, inverse=True)
    assert val(eng, h, s, 0, 0) == 2.0 and val(eng, h, s, 0, 1) == 20.0
    eng.apply_delta(h, d, inverse=False)
    assert val(eng, h, s, 0, 1) == 50.0


def test_new_formula_chain_and_undo(tmp_path):
    eng, h, s = book(tmp_path)
    d = eng.apply_cell_edits(h, s.id, [fx(1, 0, "=B1+1"), fx(2, 0, "=A2*2")])
    assert val(eng, h, s, 1, 0) == 21.0 and val(eng, h, s, 2, 0) == 42.0
    eng.apply_cell_edits(h, s.id, [nm(0, 0, 0)])
    assert val(eng, h, s, 2, 0) == 2.0
    eng.apply_delta(h, d, inverse=True)
    assert cell(eng, h, s, 1, 0) is None


def test_unknown_function_is_name_error_and_syntax_error_is_rejected(tmp_path):
    import pytest

    from gridora_engine.errors import GridoraEngineError
    eng, h, s = book(tmp_path)
    eng.apply_cell_edits(h, s.id, [fx(3, 0, "=NOSUCHFN(1)")])
    assert cell(eng, h, s, 3, 0).v.k == "err"
    with pytest.raises(GridoraEngineError) as e:
        eng.apply_cell_edits(h, s.id, [fx(4, 0, "=1+")])
    assert e.value.reason == "edit.formula_syntax"


def test_cycle_does_not_hang_and_breaking_it_recovers(tmp_path):
    eng, h, s = book(tmp_path)
    eng.apply_cell_edits(h, s.id, [fx(5, 0, "=A7+1"), fx(6, 0, "=A6+1")])
    eng.apply_cell_edits(h, s.id, [nm(6, 0, 1)])
    assert val(eng, h, s, 5, 0) == 2.0


def test_cross_sheet_dependents_reported_in_others_and_undone(tmp_path):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(_two_sheet(tmp_path))
    s1, s2 = wb.sheets[0], wb.sheets[1]
    eng.apply_cell_edits(h, s2.id, [fx(5, 0, "=Sheet1!B2*3")])
    assert val(eng, h, s2, 5, 0) == 15.0
    d = eng.apply_cell_edits(h, s1.id, [nm(1, 1, 100)])
    assert val(eng, h, s2, 5, 0) == 300.0
    assert d.others and d.others[0].sheet_id == s2.id
    eng.apply_delta(h, d, inverse=True)
    assert val(eng, h, s2, 5, 0) == 15.0 and val(eng, h, s1, 1, 1) == 5.0
    eng.apply_delta(h, d, inverse=False)
    assert val(eng, h, s2, 5, 0) == 300.0


def _two_sheet(tmp_path):
    import zipfile

    from support import xlsx_parts  # default parts already hold two sheets
    p = tmp_path / "two.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        for k, v in xlsx_parts().items():
            z.writestr(k, v)
    return p


def test_volatile_and_full_recalculate_do_not_break(tmp_path):
    eng, h, s = book(tmp_path)
    eng.apply_cell_edits(h, s.id, [fx(1, 3, "=TODAY()"), fx(1, 4, "=SUM(A1:B1)")])
    assert val(eng, h, s, 1, 4) == 22.0
    eng.recalculate(h)
    assert val(eng, h, s, 1, 4) == 22.0


def test_array_formula_is_evaluated_over_its_range_and_follows_edits(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c><c r="B1"><f t="array" ref="B1:B3">A1:A3*2</f><v>2</v></c><c r="C1"><f>SUM(B1:B3)</f><v>12</v></c></row>'
            '<row r="2"><c r="A2"><v>2</v></c><c r="B2"><v>4</v></c></row>'
            '<row r="3"><c r="A3"><v>3</v></c><c r="B3"><v>6</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "a.xlsx", sheet_doc(rows, "")))
    s = wb.sheets[0]
    d = eng.apply_cell_edits(h, s.id, [nm(1, 0, 10)])
    assert [val(eng, h, s, r, 1) for r in range(3)] == [2.0, 20.0, 6.0]
    assert val(eng, h, s, 0, 2) == 28.0  # a formula over the array range follows its members
    assert any(c.r == 1 and c.c == 1 for c in d.after)
    eng.apply_delta(h, d, inverse=True)
    assert [val(eng, h, s, r, 1) for r in range(3)] == [2.0, 4.0, 6.0] and val(eng, h, s, 0, 2) == 12.0
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    import zipfile
    xml = zipfile.ZipFile(out).read("xl/worksheets/sheet1.xml").decode()
    assert 't="array"' in xml and 'ref="B1:B3"' in xml


def test_formulas_without_cached_values_are_computed_on_first_read(tmp_path):
    """Files saved by generators (openpyxl and similar) hold formulas but no results."""
    rows = (
        '<row r="1"><c r="A1"><v>3</v></c><c r="B1"><f>A1*2</f><v /></c><c r="C1"><f>SUM(A1:B1)</f><v /></c></row>'
        '<row r="2"><c r="A2"><v>4</v></c><c r="B2"><f>A2*2</f><v /></c></row>'
    )
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "nocache.xlsx", sheet_doc(rows)))
    s = wb.sheets[0]
    assert val(eng, h, s, 0, 1) == 6
    assert val(eng, h, s, 0, 2) == 9
    assert val(eng, h, s, 1, 1) == 8


def test_cached_values_in_a_file_are_not_recomputed_on_read(tmp_path):
    """A saved result is kept as saved until something it depends on changes."""
    rows = '<row r="1"><c r="A1"><v>2</v></c><c r="B1"><f>A1*10</f><v>999</v></c></row>'
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "cached.xlsx", sheet_doc(rows)))
    assert val(eng, h, wb.sheets[0], 0, 1) == 999


def test_formula_with_an_empty_value_element_has_no_saved_result(tmp_path):
    """openpyxl writes <f>..</f><v /> for every formula; that is "no result", not a broken number."""
    rows = '<row r="1"><c r="A1"><v>5</v></c><c r="B1"><f>A1+1</f><v /></c></row>'
    eng = create_engine({})
    h, wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "emptyv.xlsx", sheet_doc(rows)))
    assert val(eng, h, wb.sheets[0], 0, 1) == 6
    assert all(i.code != "xlsx.cell_value_invalid" for i in rep.items)


def test_subtotal_101_to_111_skip_hidden_rows_but_1_to_11_do_not(tmp_path):
    hid = ' hidden="1"'
    rows = "".join(
        f'<row r="{i}"{hid if i in (2, 4) else ""}><c r="A{i}"><v>{i * 10}</v></c></row>' for i in range(1, 6)
    )
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "h.xlsx", sheet_doc(rows, "")))
    s = wb.sheets[0]
    eng.apply_cell_edits(h, s.id, [fx(10, 0, "SUBTOTAL(9,A1:A5)"), fx(11, 0, "SUBTOTAL(109,A1:A5)"), fx(12, 0, "SUBTOTAL(103,A1:A5)")])
    assert val(eng, h, s, 10, 0) == 150.0
    assert val(eng, h, s, 11, 0) == 90.0
    assert val(eng, h, s, 12, 0) == 3.0
