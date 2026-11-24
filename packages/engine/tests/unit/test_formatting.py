"""Cell formatting: change the look, number formats shown, replay of formats, export."""
from __future__ import annotations

import re
import zipfile

import pytest
from gridora_contracts.models import CellEdit, NumValue, Range
from support import make_xlsx, read_window

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError


def book(tmp_path):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx"))
    return eng, h, wb.sheets[0]


def rng(s, r0, c0, r1, c1):
    return Range(sheet_id=s.id, r0=r0, c0=c0, r1=r1, c1=c1)


def test_bold_fill_and_values_stay(tmp_path):
    eng, h, s = book(tmp_path)
    d = eng.format_cells(h, rng(s, 1, 1, 2, 1), {"bold": True, "fill_color": "#ffcc00"})
    cells = read_window(eng, h, s)
    st = eng.get_styles(h, [cells[(1, 1)].s])[0]
    assert st.bold and st.fill_color == "#FFCC00" and cells[(1, 1)].v.n == 5
    assert cells[(1, 1)].s == cells[(2, 1)].s  # same wanted look, same format id
    assert d.styles and d.styles[0].id == cells[(1, 1)].s and d.styles[0].base_id == 0
    eng.format_cells(h, rng(s, 1, 1, 1, 1), {"bold": None})  # null puts the default back
    c2 = read_window(eng, h, s)
    assert not eng.get_styles(h, [c2[(1, 1)].s])[0].bold


def test_number_format_shows_text_and_keeps_value(tmp_path):
    eng, h, s = book(tmp_path)
    eng.apply_cell_edits(h, s.id, [CellEdit(r=5, c=0, value=NumValue(n=1234567.891))])
    eng.format_cells(h, rng(s, 5, 0, 5, 0), {"number_format": "#,##0.00"})
    c = read_window(eng, h, s)[(5, 0)]
    assert c.d == "1,234,567.89" and c.v.n == 1234567.891
    eng.format_cells(h, rng(s, 5, 0, 5, 0), {"number_format": "0%"})
    assert read_window(eng, h, s)[(5, 0)].d == "123456789%"
    eng.format_cells(h, rng(s, 5, 0, 5, 0), {"number_format": None})
    assert read_window(eng, h, s)[(5, 0)].d is None


def test_undo_redo_and_replay_recreate_ids(tmp_path):
    eng, h, s = book(tmp_path)
    d1 = eng.format_cells(h, rng(s, 1, 1, 1, 1), {"italic": True})
    d2 = eng.format_cells(h, rng(s, 2, 1, 2, 1), {"bold": True})
    eng.apply_delta(h, d2, inverse=True)
    eng.apply_delta(h, d1, inverse=True)
    assert read_window(eng, h, s)[(1, 1)].s is None
    # a fresh copy replays only the second (the first was "undone"): the id it uses must exist there
    eng2, h2, s2 = book(tmp_path)
    eng2.apply_delta(h2, d2.model_copy(update={"sheet_id": s2.id}), inverse=False)
    c = read_window(eng2, h2, s2)[(2, 1)]
    assert eng2.get_styles(h2, [c.s])[0].bold
    eng2.apply_delta(h2, d1.model_copy(update={"sheet_id": s2.id}), inverse=False)  # redo of the first fills the gap
    assert eng2.get_styles(h2, [read_window(eng2, h2, s2)[(1, 1)].s])[0].italic
    assert eng2.get_styles(h2, [c.s])[0].bold


def test_date_format_makes_a_number_a_date(tmp_path):
    eng, h, s = book(tmp_path)
    eng.apply_cell_edits(h, s.id, [CellEdit(r=6, c=0, value=NumValue(n=45292))])
    eng.format_cells(h, rng(s, 6, 0, 6, 0), {"number_format": "yyyy-mm-dd"})
    assert read_window(eng, h, s)[(6, 0)].v.k == "date"


def test_export_appends_styles_and_keeps_the_rest(tmp_path):
    eng, h, s = book(tmp_path)
    eng.format_cells(h, rng(s, 1, 1, 1, 1), {"bold": True, "font_name": "Tahoma", "font_size": 14, "font_color": "#ff0000",
                                             "fill_color": "#00ff00", "halign": "center", "wrap": True, "number_format": "0.000"})
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    z = zipfile.ZipFile(out)
    xml = z.read("xl/styles.xml").decode()
    assert 'yyyy\\-mm\\-dd' in xml and '<dxfs count="1">' in xml  # untouched parts stay
    assert '<fonts count="2">' in xml and 'val="Tahoma"' in xml and "<b/>" in xml and 'rgb="FFFF0000"' in xml
    assert '<fills count="3">' in xml and 'rgb="FF00FF00"' in xml
    assert '<cellXfs count="3">' in xml and 'horizontal="center"' in xml and 'wrapText="1"' in xml
    assert re.search(r'<numFmt numFmtId="165" formatCode="0.000"/>', xml) and '<numFmts count="2">' in xml
    # the file opens again and shows what was set
    eng2 = create_engine({})
    h2, wb2, _ = eng2.import_xlsx(out)
    c = read_window(eng2, h2, wb2.sheets[0])[(1, 1)]
    st = eng2.get_styles(h2, [c.s])[0]
    assert (st.bold, st.font_name, st.font_size, st.font_color, st.fill_color, st.halign, st.wrap, st.number_format) == (
        True, "Tahoma", 14.0, "#FF0000", "#00FF00", "center", True, "0.000")


def test_csv_workbook_formats_export(tmp_path):
    from gridora_engine.csvio.options import CsvImportOptions

    f = tmp_path / "a.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    eng = create_engine({})
    h, wb = eng.import_csv(f, CsvImportOptions())
    s = wb.sheets[0]
    eng.format_cells(h, rng(s, 0, 0, 0, 1), {"bold": True})
    out = tmp_path / "o.xlsx"
    eng.export_xlsx(h, out)
    eng2 = create_engine({})
    h2, wb2, _ = eng2.import_xlsx(out)
    c = read_window(eng2, h2, wb2.sheets[0])[(0, 1)]
    assert eng2.get_styles(h2, [c.s])[0].bold


def test_bad_requests(tmp_path):
    eng, h, s = book(tmp_path)
    with pytest.raises(GridoraEngineError):
        eng.format_cells(h, rng(s, 0, 0, 1000, 100), {"bold": True})
    with pytest.raises(GridoraEngineError):
        eng.format_cells(h, rng(s, 0, 0, 0, 0), {})
    with pytest.raises(GridoraEngineError):
        eng.format_cells(h, rng(s, 0, 0, 0, 0), {"sparkle": True})
