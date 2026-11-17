from __future__ import annotations

import pytest
from support import HDR, NS, make_xlsx, read_window, sheet_doc, write_zip, xlsx_parts

from gridora_engine import create_engine


@pytest.fixture
def eng():
    return create_engine({})


def val(c):
    v = c.v
    return None if v is None else {"num": getattr(v, "n", None), "str": getattr(v, "s", None),
                                   "bool": getattr(v, "b", None), "err": getattr(v, "e", None),
                                   "date": getattr(v, "iso", None)}[v.k]


def codes(report):
    return {i.code: i for i in report.items}


def test_import_values_types_dates_formulas_styles(eng, tmp_path):
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>1.5</v></c><c r="C1" t="inlineStr"><is><t>inline</t></is></c>'
        '<c r="D1" t="str"><f>A1&amp;"x"</f><v>namex</v></c><c r="E1" t="b"><v>1</v></c><c r="F1" t="e"><v>#N/A</v></c></row>'
        '<row r="2"><c r="A2" s="1"><v>45292</v></c><c r="B2" s="1"><v>45292.5</v></c><c r="C2"><f>B1*2</f></c>'
        '<c r="D2" t="d"><v>2024-01-01</v></c><c r="E2" s="1"><v>0.5</v></c></row>'
    )
    p = make_xlsx(tmp_path / "a.xlsx", sheet_doc(rows))
    h, wb, rep = eng.import_xlsx(p, file_id="f1")
    assert wb.file_id == "f1" and wb.date_system == "1900" and wb.compat == rep and rep.source == "import"
    g = read_window(eng, h, wb.sheets[0])
    assert val(g[0, 0]) == "name" and val(g[0, 1]) == 1.5 and val(g[0, 2]) == "inline"
    assert val(g[0, 3]) == "namex" and g[0, 3].f == '=A1&"x"'
    assert val(g[0, 4]) is True and val(g[0, 5]) == "#N/A"
    assert val(g[1, 0]) == "2024-01-01" and g[1, 0].s == 1 and g[1, 0].t == "164"
    assert val(g[1, 1]) == "2024-01-01T12:00:00"
    assert g[1, 2].v is None and g[1, 2].f == "=B1*2"  # formula without a cached value
    assert val(g[1, 3]) == 45292.0  # t="d" is read as a serial number (no date style on it)
    assert (1, 4) in g and val(g[1, 4]) == "12:00:00"  # time-only for a serial below 1
    assert (wb.sheets[0].row_count, wb.sheets[0].col_count) == (2, 6)
    assert "xlsx.formulas_not_recalculated" in codes(rep)


def test_date1904_workbook(eng, tmp_path):
    wb_xml = xlsx_parts()["xl/workbook.xml"].replace("<workbookPr/>", '<workbookPr date1904="1"/>')
    rows = '<row r="1"><c r="A1" s="1"><v>1461</v></c></row>'
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "d.xlsx", sheet_doc(rows), **{"xl/workbook.xml": wb_xml}))
    assert wb.date_system == "1904"
    assert val(read_window(eng, h, wb.sheets[0])[0, 0]) == "1908-01-01"


def test_import_report_lists_preserved_parts_with_locations(eng, tmp_path):
    p = write_zip(tmp_path / "e.xlsx", xlsx_parts(extras=True))
    h, _wb, rep = eng.import_xlsx(p)
    c = codes(rep)
    for code in ("xlsx.vba_project", "xlsx.drawing", "xlsx.custom_xml", "xlsx.pivot_table"):
        item = c[code]
        assert item.status == "unsupported" and item.preserved is True and item.editable is False
        assert item.location
    assert c["xlsx.drawing"].location == "xl/drawings/drawing1.xml"
    assert rep.summary.unsupported + rep.summary.partial + rep.summary.supported == len(rep.items)
    assert eng._open[h.id].package.kind == "xlsm"


def test_xlsm_macro_workbook_preserved_not_run(eng, tmp_path):
    _h, _wb, rep = eng.import_xlsx(write_zip(tmp_path / "m.xlsx", xlsx_parts(extras=True)))
    assert codes(rep)["xlsx.vba_project"].preserved
    assert "never run" in codes(rep)["xlsx.vba_project"].message


def test_sheet_level_features_reported(eng, tmp_path):
    after = (
        '<sheetProtection sheet="1"/><autoFilter ref="A1:B2"/><mergeCells count="2"><mergeCell ref="A1:B1"/><mergeCell ref="C1:D1"/></mergeCells>'
        '<conditionalFormatting sqref="A1"><cfRule type="cellIs" priority="1" operator="equal"><formula>1</formula></cfRule></conditionalFormatting>'
        '<dataValidations count="3"><dataValidation type="whole" sqref="A1"/></dataValidations>'
        '<hyperlinks><hyperlink ref="A1" location="Sheet1!B2"/></hyperlinks>'
        '<extLst><ext uri="{A}"/><ext uri="{B}"/></extLst>'
    )
    sheet = sheet_doc('<row r="1"><c r="A1"><v>1</v></c></row>', after)
    _h, _wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "f.xlsx", sheet))
    c = codes(rep)
    assert "2 merged" in c["xlsx.merged_cells"].message and "3 data-validation" in c["xlsx.data_validation"].message
    assert "2 extension" in c["xlsx.ext_list"].message
    for code in ("xlsx.sheet_protection", "xlsx.auto_filter", "xlsx.conditional_format", "xlsx.hyperlinks"):
        assert c[code].preserved and c[code].location == "Sheet1"


def test_rtl_frozen_hidden_and_defined_names(eng, tmp_path):
    wb_xml = xlsx_parts()["xl/workbook.xml"].replace(
        '<sheet name="برگه ۲" sheetId="2" r:id="rId2"/>', '<sheet name="برگه ۲" sheetId="2" state="veryHidden" r:id="rId2"/>'
    ).replace("<calcPr", '<definedNames><definedName name="Qty">Sheet1!$B$2:$B$4</definedName>'
              '<definedName name="Loc" localSheetId="1">Sheet1!$A$1</definedName></definedNames><calcPr')
    s1 = sheet_doc('<row r="1"><c r="A1"><v>1</v></c></row>', head='<sheetViews><sheetView rightToLeft="1" workbookViewId="0"><pane xSplit="1" ySplit="2" topLeftCell="B3" state="frozen"/></sheetView></sheetViews>')
    _h, wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "v.xlsx", s1, **{"xl/workbook.xml": wb_xml}))
    s = wb.sheets[0]
    assert s.rtl is True and s.frozen.rows == 2 and s.frozen.cols == 1 and s.visible == "visible"
    assert wb.sheets[1].visible == "very_hidden" and wb.sheets[1].rtl is True  # the fixture's own sheet 2 is RTL
    names = {d.name: d for d in wb.defined_names}
    assert names["Qty"].scope == "workbook" and names["Qty"].ref == "Sheet1!$B$2:$B$4"
    assert names["Loc"].scope == wb.sheets[1].id
    c = codes(rep)
    assert c["xlsx.rtl_view"].status == "supported" and c["xlsx.frozen_panes"].status == "supported"
    assert c["xlsx.defined_name"].status == "partial" and "2 defined" in c["xlsx.defined_name"].message


def test_rich_text_and_shared_array_formulas(eng, tmp_path):
    sst = HDR + (f'<sst {NS} count="2" uniqueCount="2"><si><r><rPr><b/></rPr><t>bold </t></r><r><t>plain</t></r></si>'
                 '<si><t>x</t><rPh sb="0" eb="1"><t>PHONETIC</t></rPh></si></sst>')
    rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2"><f t="shared" ref="A2:A4" si="0">B2*2</f><v>2</v></c><c r="B2"><v>1</v></c></row>'
            '<row r="3"><c r="A3"><f t="shared" si="0"/><v>4</v></c></row>'
            '<row r="4"><c r="A4" cm="1"><f t="array" ref="A4:A5">SUM(B2:B3)</f><v>9</v></c></row>')
    h, wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "r.xlsx", sheet_doc(rows), **{"xl/sharedStrings.xml": sst}))
    g = read_window(eng, h, wb.sheets[0])
    assert val(g[0, 0]) == "bold plain" and val(g[0, 1]) == "x"  # runs joined, phonetic text skipped
    assert g[1, 0].f == "=B2*2" and g[2, 0].f is None and val(g[2, 0]) == 4.0  # child shows its cached value only
    assert g[3, 0].f == "=SUM(B2:B3)"
    c = codes(rep)
    assert "1 cell text" in c["xlsx.rich_text"].message
    assert "xlsx.shared_formula" in c and "xlsx.array_formula" in c and "xlsx.dynamic_array" in c
    sh = eng._open[h.id].sheets[0]
    assert sorted(sh.fkind.values()) == [2, 3, 4]


def test_lazy_windows_match_full_parse(eng, tmp_path):
    rows = "".join(
        f'<row r="{r}" spans="1:3"><c r="A{r}"><v>{r}</v></c><c r="B{r}" t="inlineStr"><is><t>t{r}</t></is></c>'
        f'<c r="C{r}"><f>A{r}*2</f><v>{r * 2}</v></c></row>' for r in range(1, 1201))
    p = make_xlsx(tmp_path / "big.xlsx", sheet_doc(rows))
    h, wb, _rep = eng.import_xlsx(p)
    sheet = eng._open[h.id].sheets[0]
    assert sheet.lazy is not None and not sheet.lazy.eager and (wb.sheets[0].row_count, wb.sheets[0].col_count) == (1200, 3)
    assert sheet.store.used_size() == (0, 0)  # nothing materialized at import
    mid = read_window(eng, h, wb.sheets[0], rows=10, row0=700)
    assert val(mid[700, 0]) == 701.0 and val(mid[709, 1]) == "t710"
    assert sorted(sheet.lazy.parsed_blocks) == [2]  # only the 256-row block that holds the window
    win = read_window(eng, h, wb.sheets[0], rows=1000)
    sheet.lazy.materialize_all()
    full = read_window(eng, h, wb.sheets[0], rows=1000)
    assert {k: (val(v), v.f) for k, v in win.items()} == {k: (val(v), v.f) for k, v in full.items()}
    assert len(read_window(eng, h, wb.sheets[0], rows=1000, row0=200)) == 3000


def test_index_hint_is_validated_and_falls_back(eng, tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c></row><!-- <row r="2"> decoy -->'
            '<row r="3"><c r="A3"><v>3</v></c></row>')
    h, wb, _rep = eng.import_xlsx(make_xlsx(tmp_path / "decoy.xlsx", sheet_doc(rows)))
    g = read_window(eng, h, wb.sheets[0])
    assert (val(g[0, 0]), val(g[2, 0]), (1, 0) in g) == (1.0, 3.0, False)
    assert eng._open[h.id].sheets[0].lazy.fell_back is True


def test_prefixed_namespace_sheet_uses_eager_path(eng, tmp_path):
    ns = 'xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    doc = HDR + (f'<x:worksheet {ns}><x:sheetViews><x:sheetView rightToLeft="1" workbookViewId="0"/></x:sheetViews><x:sheetData>'
                 '<x:row r="1"><x:c r="A1"><x:v>7</x:v></x:c></x:row></x:sheetData></x:worksheet>')
    h, wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "p.xlsx", doc))
    assert val(read_window(eng, h, wb.sheets[0])[0, 0]) == 7.0 and wb.sheets[0].rtl is True
    assert "xlsx.lazy_fallback" in codes(rep)


def test_non_ascending_rows_fall_back_to_full_parse(eng, tmp_path):
    rows = '<row r="2"><c r="A2"><v>2</v></c></row><row r="1"><c r="A1"><v>1</v></c></row>'
    h, wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "o.xlsx", sheet_doc(rows)))
    g = read_window(eng, h, wb.sheets[0])
    assert val(g[0, 0]) == 1.0 and val(g[1, 0]) == 2.0 and "xlsx.lazy_fallback" in codes(rep)


def test_invalid_cell_values_become_errors_and_are_recorded_as_findings(eng, tmp_path):
    rows = ('<row r="1"><c r="A1"><v>abc</v></c><c r="B1" t="s"><v>99</v></c><c r="C1" t="e"><v>#WHAT!</v></c>'
            '<c r="D1" t="e"><v>#SPILL!</v></c><c r="E1" t="d"><v>not a date</v></c></row>')
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "bad.xlsx", sheet_doc(rows)))
    g = read_window(eng, h, wb.sheets[0])
    assert [val(g[0, c]) for c in range(5)] == ["#VALUE!", "#VALUE!", "#VALUE!", "#SPILL!", "#VALUE!"]
    f = eng._open[h.id].findings[0]
    assert f.counts == {"xlsx.cell_value_invalid": 3, "xlsx.error_value.unmapped": 1}


def test_close_releases_spool_and_package(eng, tmp_path):
    h, _wb, _ = eng.import_xlsx(write_zip(tmp_path / "c.xlsx", xlsx_parts()))
    state = eng._open[h.id]
    src = state.sheets[0].lazy.source
    eng.close(h)
    assert src.mm is None and state.package is None
    eng.close(h)  # closing twice is a no-op


def test_formula_cells_without_value_and_empty_sheet(eng, tmp_path):
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "e.xlsx", sheet_doc("")))
    assert (wb.sheets[0].row_count, wb.sheets[0].col_count) == (0, 0) and read_window(eng, h, wb.sheets[0]) == {}
    selfclosing = HDR + f"<worksheet {NS}><sheetData/></worksheet>"
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "e2.xlsx", selfclosing))
    assert read_window(eng, h, wb.sheets[0]) == {}


def test_chartsheet_is_preserved_and_listed_in_report(eng, tmp_path):
    parts = xlsx_parts()
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        "</sheets>", '<sheet name="Chart1" sheetId="3" r:id="rId9"/></sheets>')
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "</Relationships>", '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chartsheet" Target="chartsheets/sheet1.xml"/></Relationships>')
    parts["xl/chartsheets/sheet1.xml"] = HDR + "<chartsheet/>"
    _h, wb, rep = eng.import_xlsx(write_zip(tmp_path / "cs.xlsx", parts))
    assert [s.name for s in wb.sheets] == ["Sheet1", "برگه ۲"] and codes(rep)["xlsx.chartsheet"].location == "Chart1"


def test_full_calc_on_load_flag_is_reported(eng, tmp_path):
    wb_xml = xlsx_parts()["xl/workbook.xml"].replace('<calcPr calcId="191029"/>', '<calcPr calcId="191029" fullCalcOnLoad="1"/>')
    _h, _wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "f.xlsx", sheet_doc(""), **{"xl/workbook.xml": wb_xml}))
    assert "xlsx.full_calc_on_load" in codes(rep)
    _h, _wb, rep = eng.import_xlsx(make_xlsx(tmp_path / "g.xlsx", sheet_doc("")))
    assert "xlsx.full_calc_on_load" not in codes(rep)
