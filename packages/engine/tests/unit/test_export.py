from __future__ import annotations

import zipfile

import pytest
from gridora_contracts.models import CellEdit, NumValue, StrValue
from support import (
    HDR,
    NS,
    PKG_REL,
    R,
    make_xlsx,
    read_parts,
    read_window,
    sheet_doc,
    write_zip,
    xlsx_parts,
)

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError
from gridora_engine.limits import ResourceLimits
from gridora_engine.package.parts import PackageModel


def num(r, c, n):
    return CellEdit(r=r, c=c, value=NumValue(n=n))


def txt(r, c, s):
    return CellEdit(r=r, c=c, value=StrValue(s=s))


def codes(rep):
    return {i.code: i for i in rep.items}


def window_values(eng, h, sheet, rows=1000, cols=60):
    return {k: (c.v.model_dump_json() if c.v else None, c.f, c.s) for k, c in read_window(eng, h, sheet, rows=rows, cols=cols).items()}


def reimport(eng, path):
    h, wb, rep = eng.import_xlsx(path)
    return h, wb, rep


def sheets_rows(n=700):
    return "".join(
        f'<row r="{r}" spans="1:3" ht="18" customHeight="1"><c r="A{r}"><v>{r}</v></c><c r="B{r}" s="1" t="inlineStr"><is><t>t{r}</t></is></c>'
        f'<c r="C{r}"><f>A{r}*2</f><v>{r * 2}</v></c></row>' for r in range(1, n + 1))


def test_export_without_edits_is_a_byte_equal_copy(tmp_path):
    src = write_zip(tmp_path / "in.xlsx", xlsx_parts(extras=True))
    eng = create_engine({})
    h, _wb, _ = eng.import_xlsx(src)
    rep = eng.export_xlsx(h, tmp_path / "out.xlsx")
    a, b = read_parts(src), read_parts(tmp_path / "out.xlsx")
    assert list(a) == list(b) and all(a[n] == b[n] for n in a)
    assert rep.source == "export" and set(codes(rep)) == {"xlsx.macro_enabled_extension"}


def test_edit_rebuilds_only_the_edited_rows_everything_else_is_byte_equal(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows()), extras=True)
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    s = wb.sheets[0]
    eng.apply_cell_edits(h, s.id, [num(9, 0, -5.5), txt(9, 1, "سلام & <x>"), CellEdit(r=300, c=2)])
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    a, b = read_parts(src), read_parts(out)
    assert list(a) == list(b)
    # every other part is byte-equal (unknown parts included); workbook.xml only gains fullCalcOnLoad (the sheet has formulas)
    assert all(a[n] == b[n] for n in a if n not in ("xl/worksheets/sheet1.xml", "xl/workbook.xml"))
    assert b["xl/workbook.xml"].replace(b' fullCalcOnLoad="1"', b"") == a["xl/workbook.xml"]
    old, new = a["xl/worksheets/sheet1.xml"], b["xl/worksheets/sheet1.xml"]
    rows_old = old.split(b"</row>")
    rows_new = new.split(b"</row>")
    assert len(rows_old) == len(rows_new)
    changed = [i for i, (x, y) in enumerate(zip(rows_old, rows_new, strict=True)) if x != y]
    assert changed == [9, 300]  # only the two rows with edits differ
    assert b'spans="1:3"' in rows_new[9] and b'ht="18"' in rows_new[9]  # row attributes kept; spans recomputed
    assert old.split(b"<row r=\"10\"")[0] == new.split(b"<row r=\"10\"")[0]  # prefix identical


def test_exported_file_reimports_with_exactly_the_live_state(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows()))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    s = wb.sheets[0]
    eng.apply_cell_edits(h, s.id, [num(0, 0, 1e300), txt(1, 1, "a_x000D_b\r\nc"), num(900, 5, 7), CellEdit(r=2, c=0),
                                   txt(3, 1, " lead & trail "), txt(4, 1, "")])
    live = window_values(eng, h, s)
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    eng2 = create_engine({})
    h2, wb2, _ = reimport(eng2, out)
    again = window_values(eng2, h2, wb2.sheets[0])
    assert again == live
    assert wb2.sheets[0].row_count == 901 and wb2.sheets[0].col_count >= 6
    g = read_window(eng2, h2, wb2.sheets[0])
    assert g[1, 1].v.s == "a_x000D_b\r\nc" and g[3, 1].v.s == " lead & trail "  # escapes round-trip exactly


def test_edited_text_is_written_as_inline_string_and_roundtrips(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc('<row r="1"><c r="A1"><v>1</v></c></row>'))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [txt(0, 0, "ی ک \x01 \u200f"), txt(5, 1, "x")])
    out = tmp_path / "out.xlsx"
    rep = eng.export_xlsx(h, out)
    xml = read_parts(out)["xl/worksheets/sheet1.xml"]
    assert b't="inlineStr"' in xml and b"_x0001_" in xml and "ی ک".encode() in xml
    assert codes(rep)["xlsx.inline_strings"].message.startswith("2 edited text")
    eng2 = create_engine({})
    h2, wb2, _ = reimport(eng2, out)
    g = read_window(eng2, h2, wb2.sheets[0])
    assert g[0, 0].v.s == "ی ک \x01 \u200f" and g[5, 1].v.s == "x"


def test_new_rows_and_dimension_and_self_closing_sheetdata(tmp_path):
    eng = create_engine({})
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc('<row r="2"><c r="A2"><v>1</v></c></row><row r="5"><c r="A5"><v>2</v></c></row>', head='<dimension ref="A2:A5"/>'))
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 9), num(3, 4, 8), num(9, 2, 7)])  # rows 1, 4 new; row 10 beyond; col E
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    xml = read_parts(out)["xl/worksheets/sheet1.xml"].decode()
    assert xml.index('<row r="1"') < xml.index('<row r="2"') < xml.index('<row r="4"') < xml.index('<row r="5"') < xml.index('<row r="10"')
    assert '<dimension ref="A2:E10"/>' in xml
    eng2 = create_engine({})
    h2, wb2, _ = reimport(eng2, out)
    assert window_values(eng2, h2, wb2.sheets[0]) == window_values(eng, h, wb.sheets[0])
    # an empty, self-closing <sheetData/> gets rows too
    empty = make_xlsx(tmp_path / "e.xlsx", HDR + f"<worksheet {NS}><sheetData/></worksheet>")
    h3, wb3, _ = eng.import_xlsx(empty)
    eng.apply_cell_edits(h3, wb3.sheets[0].id, [num(0, 0, 1)])
    eng.export_xlsx(h3, tmp_path / "e_out.xlsx")
    _h4, wb4, _ = reimport(create_engine({}), tmp_path / "e_out.xlsx")
    assert wb4.sheets[0].row_count == 1


def test_formula_cells_are_kept_or_replaced_exactly(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows(20)))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    s = wb.sheets[0]
    eng.apply_cell_edits(h, s.id, [num(2, 2, 77)])  # overwrite one formula with a value; A3 stays
    out = tmp_path / "out.xlsx"
    eng.export_xlsx(h, out)
    xml = read_parts(out)["xl/worksheets/sheet1.xml"].decode()
    assert "<f>A4*2</f>" in xml and "<f>A3*2</f>" not in xml  # other rows keep their formulas verbatim
    eng2 = create_engine({})
    h2, wb2, _ = reimport(eng2, out)
    g = read_window(eng2, h2, wb2.sheets[0])
    assert g[2, 2].v.n == 77.0 and g[2, 2].f is None and g[3, 2].f == "=A4*2"


def test_edit_in_workbook_with_formulas_reports_stale_values_and_sets_full_calc(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows(20)))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 100)])
    out = tmp_path / "out.xlsx"
    rep = eng.export_xlsx(h, out)
    c = codes(rep)
    assert "xlsx.cached_values_stale" not in c  # everything was recalculated by Gridora
    assert "xlsx.full_calc_on_load_set" in c
    assert b'fullCalcOnLoad="1"' in read_parts(out)["xl/workbook.xml"]
    assert 'calcPr calcId="191029" fullCalcOnLoad="1"' in read_parts(out)["xl/workbook.xml"].decode()
    # no formulas, nothing stale; no edits, nothing reported
    plain = make_xlsx(tmp_path / "p.xlsx", sheet_doc('<row r="1"><c r="A1"><v>1</v></c></row>'))
    h2, wb2, _ = eng.import_xlsx(plain)
    eng.apply_cell_edits(h2, wb2.sheets[0].id, [num(0, 0, 2)])
    rep2 = eng.export_xlsx(h2, tmp_path / "p_out.xlsx")
    assert "xlsx.cached_values_stale" not in codes(rep2) and b"fullCalcOnLoad" not in read_parts(tmp_path / "p_out.xlsx")["xl/workbook.xml"]


def test_full_calc_on_load_is_inserted_when_calcpr_is_missing(tmp_path):
    wb_xml = xlsx_parts()["xl/workbook.xml"].replace('<calcPr calcId="191029"/>', "")
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows(3)), **{"xl/workbook.xml": wb_xml})
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 5)])
    eng.export_xlsx(h, tmp_path / "o.xlsx")
    assert read_parts(tmp_path / "o.xlsx")["xl/workbook.xml"].decode().endswith('<calcPr fullCalcOnLoad="1"/></workbook>')


def _with_calc_chain(tmp_path, rows):
    parts = xlsx_parts()
    parts["xl/worksheets/sheet1.xml"] = sheet_doc(rows)
    parts["xl/calcChain.xml"] = HDR + f'<calcChain {NS}><c r="C1" i="1"/></calcChain>'
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "</Relationships>", f'<Relationship Id="rId9" Type="{R}/calcChain" Target="calcChain.xml"/></Relationships>')
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>", '<Override PartName="/xl/calcChain.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml"/></Types>')
    return write_zip(tmp_path / "cc.xlsx", parts)


def test_calc_chain_is_dropped_only_when_formulas_change(tmp_path):
    rows = '<row r="1"><c r="A1"><v>2</v></c><c r="B1"><v>3</v></c><c r="C1"><f>A1*2</f><v>4</v></c></row>'
    src = _with_calc_chain(tmp_path, rows)
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 1, 9)])  # constant only: chain is still valid
    out = tmp_path / "keep.xlsx"
    rep = eng.export_xlsx(h, out)
    assert "xl/calcChain.xml" in read_parts(out) and "xlsx.calc_chain_dropped" not in codes(rep)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 2, 1)])  # the formula cell is overwritten
    out2 = tmp_path / "drop.xlsx"
    rep2 = eng.export_xlsx(h, out2)
    parts = read_parts(out2)
    assert "xl/calcChain.xml" not in parts and b"calcChain" not in parts["xl/_rels/workbook.xml.rels"]
    assert b"calcChain" not in parts["[Content_Types].xml"] and "xlsx.calc_chain_dropped" in codes(rep2)
    with PackageModel.open(out2, ResourceLimits()) as m:  # the package is still valid and complete
        assert m.kind == "xlsx" and len(m.relationships("xl/workbook.xml")) == 4
    original = read_parts(src)
    assert all(original[n] == parts[n] for n in parts if n in original and n not in ("xl/worksheets/sheet1.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml", "xl/workbook.xml"))


def test_edits_inside_preserved_part_sources_are_reported(tmp_path):
    parts = xlsx_parts(extras=True)
    parts["xl/worksheets/sheet1.xml"] = sheet_doc(sheets_rows(12), '<tableParts count="1"><tablePart r:id="rId7"/></tableParts>')
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = HDR + (
        f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId7" Type="{R}/table" Target="../tables/table1.xml"/></Relationships>')
    parts["xl/tables/table1.xml"] = HDR + f'<table {NS} id="1" name="T" ref="A1:B5"/>'
    parts["xl/pivotCache/pivotCacheDefinition1.xml"] = HDR + (
        f'<pivotCacheDefinition {NS}><cacheSource type="worksheet"><worksheetSource ref="A1:C12" sheet="Sheet1"/></cacheSource></pivotCacheDefinition>')
    parts["xl/pivotCache/pivotCacheDefinition2.xml"] = HDR + (
        f'<pivotCacheDefinition {NS}><cacheSource type="worksheet"><worksheetSource name="Table1"/></cacheSource></pivotCacheDefinition>')
    parts["xl/charts/chart1.xml"] = HDR + (
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:plotArea><c:ser><c:val><c:numRef>'
        "<c:f>Sheet1!$A$1:$A$12</c:f></c:numRef></c:val></c:ser><c:ser><c:val><c:numRef><c:f>'برگه ۲'!$A$1</c:f></c:numRef></c:val></c:ser>"
        "</c:plotArea></c:chart></c:chartSpace>")
    src = write_zip(tmp_path / "in.xlsx", parts)
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(2, 1, 5), num(4, 0, 6)])  # B3: table + pivot source; A5: also inside the chart range
    rep = eng.export_xlsx(h, tmp_path / "out.xlsx")
    c = codes(rep)
    assert c["xlsx.table.edited_inside"].location == "Sheet1!A1:B5"
    assert c["xlsx.pivot_table.source_edited"].location == "Sheet1!A1:C12"
    assert c["xlsx.chart.source_edited"].location == "xl/charts/chart1.xml"
    assert c["xlsx.preserved_parts_not_assessed"].message.startswith("1 preserved part")
    # edits elsewhere (outside the table, source and charted cells) report nothing about those parts
    h2, wb2, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h2, wb2.sheets[0].id, [num(30, 6, 5)])
    c2 = codes(eng.export_xlsx(h2, tmp_path / "out2.xlsx"))
    assert not ({"xlsx.table.edited_inside", "xlsx.pivot_table.source_edited", "xlsx.chart.source_edited"} & set(c2))


def test_xlsm_export_keeps_vba_and_says_to_use_xlsm_extension(tmp_path):
    src = write_zip(tmp_path / "in.xlsx", xlsx_parts(extras=True))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 3)])
    out = tmp_path / "out.xlsm"
    rep = eng.export_xlsx(h, out)
    a, b = read_parts(src), read_parts(out)
    assert a["xl/vbaProject.bin"] == b["xl/vbaProject.bin"] and a["[Content_Types].xml"] == b["[Content_Types].xml"]
    assert ".xlsm" in codes(rep)["xlsx.macro_enabled_extension"].message


def test_csv_workbook_exports_as_new_xlsx(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("نام,تعداد\nعلی,3\n=SUM(A1),2.5\n\"a & b\",\n", encoding="utf-8")
    eng = create_engine({})
    h, wb = eng.import_csv(p, CsvImportOptions())
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(3, 1, 9)])
    out = tmp_path / "out.xlsx"
    rep = eng.export_xlsx(h, out)
    assert "xlsx.generated_from_csv" in codes(rep) and "xlsx.inline_strings" in codes(rep)
    eng2 = create_engine({})
    h2, wb2, _rep2 = reimport(eng2, out)
    assert window_values(eng2, h2, wb2.sheets[0]) == window_values(eng, h, wb.sheets[0])
    assert wb2.sheets[0].name == "Sheet1"
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None and "xl/styles.xml" in z.namelist()


def test_unpatchable_sheet_layout_is_refused_for_export_with_a_typed_error(tmp_path):
    ns = 'xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    doc = HDR + f'<x:worksheet {ns}><x:sheetData><x:row r="1"><x:c r="A1"><x:v>7</x:v></x:c></x:row></x:sheetData></x:worksheet>'
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "p.xlsx", doc))
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 1)])
    with pytest.raises(GridoraEngineError) as e:
        eng.export_xlsx(h, tmp_path / "o.xlsx")
    assert e.value.code == "unsupported_workbook" and e.value.reason == "export.sheet_not_patchable"
    assert not (tmp_path / "o.xlsx").exists() and str(tmp_path) not in str(e.value)
    # ... but an unedited workbook of the same layout exports fine
    h2, _wb2, _ = eng.import_xlsx(make_xlsx(tmp_path / "q.xlsx", doc))
    eng.export_xlsx(h2, tmp_path / "ok.xlsx")


def test_lazily_found_anomalies_appear_in_the_export_report(tmp_path):
    rows = '<row r="1"><c r="A1"><v>abc</v></c><c r="B1" t="e"><v>#WHAT!</v></c></row>'
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "in.xlsx", sheet_doc(rows)))
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(5, 0, 1)])  # loads block 0 (lazy parse records the anomalies)
    rep = eng.export_xlsx(h, tmp_path / "o.xlsx")
    assert "xlsx.cell_value_invalid" in codes(rep) and "xlsx.error_value.unmapped" in codes(rep)


def test_export_is_repeatable_and_does_not_change_the_workbook(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows(30)))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(3, 0, 1)])
    eng.export_xlsx(h, tmp_path / "a.xlsx")
    eng.export_xlsx(h, tmp_path / "b.xlsx")
    assert read_parts(tmp_path / "a.xlsx") == read_parts(tmp_path / "b.xlsx")
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(4, 0, 1)])
    eng.export_xlsx(h, tmp_path / "c.xlsx")
    assert read_parts(tmp_path / "c.xlsx") != read_parts(tmp_path / "a.xlsx")


def test_undo_back_to_the_imported_state_exports_the_original_bytes(tmp_path):
    src = make_xlsx(tmp_path / "in.xlsx", sheet_doc(sheets_rows(30)), extras=True)
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(src)
    d = eng.apply_cell_edits(h, wb.sheets[0].id, [num(3, 0, 1), txt(4, 1, "z")])
    eng.apply_delta(h, d, inverse=True)
    eng.export_xlsx(h, tmp_path / "o.xlsx")
    a, b = read_parts(src), read_parts(tmp_path / "o.xlsx")
    assert all(a[n] == b[n] for n in a)  # nothing is dirty again: a verbatim copy


def _formula_wb(tmp_path, body):
    rows = f'<row r="1"><c r="A1"><v>1</v></c>{body}</row>'
    return make_xlsx(tmp_path / "f.xlsx", sheet_doc(rows))


def test_unrecalculable_formulas_are_reported_as_stale(tmp_path):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(_formula_wb(tmp_path, '<c r="B1"><f>NOSUCHFN(A1)</f><v>7</v></c><c r="C1"><f>B1+1</f><v>8</v></c>'))
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 2)])
    c = codes(eng.export_xlsx(h, tmp_path / "o.xlsx"))
    assert "xlsx.cached_values_stale" in c and "1 formula cell" in c["xlsx.cached_values_stale"].message
    assert "formula.unsupported_function" in c


def test_circular_formulas_are_reported(tmp_path):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(_formula_wb(tmp_path, '<c r="B1"><f>C1+1</f><v>1</v></c><c r="C1"><f>B1+1</f><v>2</v></c>'))
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 2)])
    eng.recalculate(h)
    assert "formula.circular" in codes(eng.export_xlsx(h, tmp_path / "o.xlsx"))


def test_calendar_mode_is_reported_for_date_formulas(tmp_path):
    eng = create_engine({})  # Jalali by default
    h, wb, _ = eng.import_xlsx(_formula_wb(tmp_path, '<c r="B1"><f>YEAR(A1)</f><v>1900</v></c>'))
    eng.apply_cell_edits(h, wb.sheets[0].id, [num(0, 0, 45371)])
    assert "formula.calendar_mode" in codes(eng.export_xlsx(h, tmp_path / "o.xlsx"))
    eng2 = create_engine({"calendar": "gregorian"})
    h2, wb2, _ = eng2.import_xlsx(_formula_wb(tmp_path, '<c r="B1"><f>YEAR(A1)</f><v>1900</v></c>'))
    eng2.apply_cell_edits(h2, wb2.sheets[0].id, [num(0, 0, 45371)])
    assert "formula.calendar_mode" not in codes(eng2.export_xlsx(h2, tmp_path / "o2.xlsx"))
