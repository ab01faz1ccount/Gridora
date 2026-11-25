"""Insert / delete rows and columns: cells, formulas, undo, export round trip and refusals."""
from __future__ import annotations

import pytest
from gridora_contracts.models import CellEdit, SheetStructureDelta, Window
from support import make_xlsx, sheet_doc

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError

ROWS = (
    '<row r="1" ht="30" customHeight="1"><c r="A1"><v>1</v></c><c r="B1"><f>A1*2</f><v>2</v></c></row>'
    '<row r="2"><c r="A2"><v>10</v></c><c r="B2"><f>SUM(A1:A3)</f><v>111</v></c></row>'
    '<row r="3"><c r="A3"><v>100</v></c><c r="B3"><f>A3+A1</f><v>101</v></c></row>'
)


def shift(eng, h, sheet_id, axis, op, at, count):
    return eng.apply_structure_change(h, {
        "type": "axis_shift", "sheet_id": sheet_id, "axis": axis, "op": op, "at": at, "count": count})


def book(tmp_path, rows=ROWS, children="", head=""):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows, children, head)))
    return eng, h, wb.sheets[0]


def snap(eng, h, s, rows=12, cols=6):
    w = eng.get_cells(h, s.id, Window(row0=0, col0=0, rows=rows, cols=cols))
    return {(c.r, c.c): (c.f, c.v.n if c.v and c.v.k == "num" else getattr(c.v, "e", None)) for c in w.cells}


def test_insert_rows_moves_cells_and_rewrites_formulas(tmp_path):
    eng, h, s = book(tmp_path)
    shift(eng, h, s.id, "row", "insert", 1, 2)
    g = snap(eng, h, s)
    assert g[(0, 0)][1] == 1 and (1, 0) not in g and (2, 0) not in g
    assert g[(3, 0)][1] == 10 and g[(4, 0)][1] == 100
    assert g[(3, 1)] == ("=SUM(A1:A5)", 111)  # the range grew over the inserted rows
    assert g[(4, 1)] == ("=A5+A1", 101)


def test_delete_rows_makes_ref_errors_and_shrinks_ranges(tmp_path):
    eng, h, s = book(tmp_path)
    shift(eng, h, s.id, "row", "delete", 2, 1)  # delete row 3 (A3 / B3)
    g = snap(eng, h, s)
    assert g[(1, 1)] == ("=SUM(A1:A2)", 11)
    assert (2, 0) not in g


def test_undo_and_redo_restore_everything_exactly(tmp_path):
    eng, h, s = book(tmp_path)
    before = snap(eng, h, s)
    for axis, op, at, n in [("row", "delete", 0, 1), ("row", "delete", 1, 2), ("col", "insert", 0, 2), ("row", "insert", 1, 3)]:
        before = snap(eng, h, s)
        d = shift(eng, h, s.id, axis, op, at, n)
        assert isinstance(d, SheetStructureDelta)
        after = snap(eng, h, s)
        assert after != before
        eng.apply_delta(h, d, inverse=True)
        assert snap(eng, h, s) == before, (axis, op)
        eng.apply_delta(h, d, inverse=False)
        assert snap(eng, h, s) == after, (axis, op, "redo")
        eng.apply_delta(h, d, inverse=True)


def test_clipped_range_comes_back_after_undo(tmp_path):
    eng, h, s = book(tmp_path)
    eng.apply_cell_edits(h, s.id, [CellEdit(r=0, c=3, formula="=SUM(A3:A9)")])  # starts inside the deleted row
    before = snap(eng, h, s)
    d = shift(eng, h, s.id, "row", "delete", 2, 1)
    assert snap(eng, h, s)[(0, 3)][0] == "=SUM(A3:A8)"
    eng.apply_delta(h, d, inverse=True)
    assert snap(eng, h, s) == before


def test_columns(tmp_path):
    eng, h, s = book(tmp_path)
    d = shift(eng, h, s.id, "col", "insert", 1, 1)
    g = snap(eng, h, s)
    assert g[(0, 2)] == ("=A1*2", 2) and (0, 1) not in g
    eng.apply_delta(h, d, inverse=True)
    d = shift(eng, h, s.id, "col", "delete", 0, 1)  # delete column A: B's formulas lose their input
    g = snap(eng, h, s)
    assert g[(0, 0)][0] == "=#REF!*2"
    eng.apply_delta(h, d, inverse=True)
    assert snap(eng, h, s)[(0, 1)] == ("=A1*2", 2)


def test_other_sheets_and_shared_formulas_follow(tmp_path):
    from support import HDR, NS, write_zip, xlsx_parts

    parts = xlsx_parts()
    parts["xl/worksheets/sheet1.xml"] = sheet_doc(
        '<row r="1"><c r="A1"><v>1</v></c><c r="B1"><f t="shared" ref="B1:B3" si="0">A1*2</f><v>2</v></c></row>'
        '<row r="2"><c r="A2"><v>10</v></c><c r="B2"><f t="shared" si="0"/><v>20</v></c></row>'
        '<row r="3"><c r="A3"><v>100</v></c><c r="B3"><f t="shared" si="0"/><v>200</v></c></row>')
    parts["xl/worksheets/sheet2.xml"] = HDR + (
        f"<worksheet {NS}><sheetData>"
        '<row r="1"><c r="A1"><f>Sheet1!A3+SUM(Sheet1!B1:B3)</f><v>322</v></c></row></sheetData></worksheet>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(write_zip(tmp_path / "two.xlsx", parts))
    s1, s2 = wb.sheets
    d = shift(eng, h, s1.id, "row", "insert", 1, 1)
    g1, g2 = snap(eng, h, s1), snap(eng, h, s2)
    assert g1[(0, 1)][0] == "=A1*2" and g1[(2, 1)][0] == "=A3*2" and g1[(3, 1)][0] == "=A4*2"  # each child follows
    assert g2[(0, 0)] == ("=Sheet1!A4+SUM(Sheet1!B1:B4)", 322)
    out = tmp_path / "o.xlsx"
    eng.export_xlsx(h, out)
    h2, wb2, _ = eng.import_xlsx(out)
    assert snap(eng, h2, wb2.sheets[1])[(0, 0)] == ("=Sheet1!A4+SUM(Sheet1!B1:B4)", 322)
    eng.apply_delta(h, d, inverse=True)
    assert snap(eng, h, s2)[(0, 0)] == ("=Sheet1!A3+SUM(Sheet1!B1:B3)", 322)
    assert snap(eng, h, s1)[(2, 1)] == ("=A3*2", 200)


def test_refuses_workbooks_with_extras(tmp_path):
    from support import write_zip, xlsx_parts

    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(write_zip(tmp_path / "e.xlsx", xlsx_parts(extras=True)))
    with pytest.raises(GridoraEngineError) as e:  # merged cells, a conditional format, a drawing, a pivot cache
        shift(eng, h, wb.sheets[0].id, "row", "insert", 0, 1)
    assert e.value.reason == "structure.unsupported_feature"
    with pytest.raises(GridoraEngineError):  # the plain second sheet is refused too: the package has a pivot cache
        shift(eng, h, wb.sheets[1].id, "row", "insert", 0, 1)


def test_refuses_sheets_with_merged_cells_and_charts(tmp_path):
    eng, h, s = book(tmp_path, children='<mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells>')
    with pytest.raises(GridoraEngineError) as e:
        shift(eng, h, s.id, "row", "insert", 0, 1)
    assert e.value.reason == "structure.unsupported_feature" and e.value.code == "operation_conflict"
    assert snap(eng, h, s)[(0, 0)][1] == 1  # nothing changed


def test_export_round_trip_keeps_row_heights_and_values(tmp_path):
    eng, h, s = book(tmp_path)
    shift(eng, h, s.id, "row", "insert", 0, 1)
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    h2, wb2, _ = eng.import_xlsx(out)
    s2 = wb2.sheets[0]
    g = snap(eng, h2, s2)
    assert g[(1, 0)][1] == 1 and g[(1, 1)] == ("=A2*2", 2)
    assert g[(2, 1)][0] == "=SUM(A2:A4)"
    import zipfile

    xml = zipfile.ZipFile(out).read("xl/worksheets/sheet1.xml").decode()
    assert '<row r="2" ht="30" customHeight="1">' in xml  # the height moved with its row
    assert '<row r="1"' not in xml


def test_limits(tmp_path):
    eng, h, s = book(tmp_path)
    with pytest.raises(GridoraEngineError):
        shift(eng, h, s.id, "row", "insert", 0, 0)
    with pytest.raises(GridoraEngineError):
        shift(eng, h, s.id, "col", "delete", 16380, 10)


def test_many_rows_and_columns_undo_and_random_operations(tmp_path):
    import random

    rows = "".join(
        f'<row r="{r}">' + "".join(f'<c r="{c}{r}"><v>{r * 10 + i}</v></c>' for i, c in enumerate("ABCD")) + "</row>"
        for r in range(1, 701)
    ) + '<row r="701"><c r="A701"><f>SUM(A1:A700)</f><v>0</v></c><c r="B701"><f>B2+D700</f><v>0</v></c></row>'
    eng, h, s = book(tmp_path, rows)
    eng.recalculate(h)  # the file's cached results are stale; start from computed values
    rng = random.Random(7)
    stack = []
    for _ in range(14):
        axis = rng.choice(["row", "col"])
        op = rng.choice(["insert", "delete"])
        at = rng.randrange(0, 700 if axis == "row" else 4)
        before = snap(eng, h, s, 760, 12)
        d = shift(eng, h, s.id, axis, op, at, rng.randrange(1, 4))
        stack.append((d, before))
    for d, before in reversed(stack):
        eng.apply_delta(h, d, inverse=True)
        assert snap(eng, h, s, 760, 12) == before
    for d, _b in stack:
        eng.apply_delta(h, d, inverse=False)
    out = tmp_path / "many.xlsx"
    eng.export_xlsx(h, out)
    h2, wb2, _ = eng.import_xlsx(out)
    assert snap(eng, h2, wb2.sheets[0], 760, 12) == snap(eng, h, s, 760, 12)


def test_column_widths_and_hidden_rows_follow(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c></row><row r="2" hidden="1"><c r="A2"><v>2</v></c></row>'
            '<row r="3"><c r="A3"><f>SUBTOTAL(109,A1:A2)</f><v>0</v></c></row>')
    head = '<cols><col min="2" max="2" width="30" customWidth="1"/><col min="4" max="5" width="12" customWidth="1"/></cols>'
    eng = create_engine({})
    from support import HDR, NS, make_xlsx

    xml = HDR + f"<worksheet {NS}>{head}<sheetData>{rows}</sheetData></worksheet>"
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "w.xlsx", xml))
    s = wb.sheets[0]
    shift(eng, h, s.id, "col", "insert", 0, 1)
    shift(eng, h, s.id, "row", "insert", 0, 2)
    assert snap(eng, h, s)[(4, 1)][1] == 1  # the hidden row (now row 4) is still skipped by SUBTOTAL(109)
    out = tmp_path / "w2.xlsx"
    eng.export_xlsx(h, out)
    import zipfile

    x = zipfile.ZipFile(out).read("xl/worksheets/sheet1.xml").decode()
    assert '<col min="3" max="3" width="30"' in x and '<col min="5" max="6" width="12"' in x
    assert '<row r="4" hidden="1">' in x
