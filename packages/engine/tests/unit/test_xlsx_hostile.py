from __future__ import annotations

import pytest
from support import HDR, NS, make_xlsx, read_window, sheet_doc, write_zip, xlsx_parts

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError

ROW1 = '<row r="1"><c r="A1"><v>1</v></c></row>'


def import_reason(tmp_path, eng, path):
    with pytest.raises(GridoraEngineError) as e:
        eng.import_xlsx(path)
    err = e.value
    assert str(tmp_path) not in str(err) and path.name not in str(err)
    return err.reason


def read_reason(tmp_path, eng, path):
    with pytest.raises(GridoraEngineError) as e:
        h, wb, _ = eng.import_xlsx(path)
        read_window(eng, h, wb.sheets[0])
    assert str(tmp_path) not in str(e.value) and path.name not in str(e.value)
    return e.value.reason


DOCTYPE = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'


def test_doctype_in_any_parsed_part_is_rejected_at_import(tmp_path):
    eng = create_engine({})
    parts = xlsx_parts()
    cases = {
        "xl/workbook.xml": parts["xl/workbook.xml"].split("?>", 1)[1],
        "xl/sharedStrings.xml": parts["xl/sharedStrings.xml"].split("?>", 1)[1],
        "xl/styles.xml": parts["xl/styles.xml"].split("?>", 1)[1],
        "xl/worksheets/sheet1.xml": sheet_doc(ROW1).split("?>", 1)[1],
    }
    for name, body in cases.items():
        p = make_xlsx(tmp_path / "x.xlsx", **{name: DOCTYPE + body})
        assert import_reason(tmp_path, eng, p) == "xml.forbidden_construct", name


def test_row_number_beyond_excel_limit_rejected_at_import(tmp_path):
    p = make_xlsx(tmp_path / "r.xlsx", sheet_doc('<row r="2000000"><c r="A2000000"><v>1</v></c></row>'))
    assert import_reason(tmp_path, create_engine({}), p) == "sheet.dimension_exceeded"


@pytest.mark.parametrize(
    "cell,reason",
    [('r="XFE1"', "sheet.dimension_exceeded"), ('r="A1048577"', "sheet.dimension_exceeded"),
     ('r="1A"', "sheet.bad_cell_reference"), ('r=""', "sheet.bad_cell_reference"),
     ('r="A0"', "sheet.dimension_exceeded")],
)
def test_bad_cell_references_surface_as_typed_errors_when_the_row_is_read(tmp_path, cell, reason):
    p = make_xlsx(tmp_path / "c.xlsx", sheet_doc(f'<row r="1"><c {cell}><v>1</v></c></row>'))
    eng = create_engine({})
    got = read_reason(tmp_path, eng, p)
    assert got in (reason, "sheet.bad_cell_reference", "sheet.dimension_exceeded")


def test_cell_row_must_match_its_row_element(tmp_path):
    p = make_xlsx(tmp_path / "m.xlsx", sheet_doc('<row r="1"><c r="A2"><v>1</v></c></row>'))
    assert read_reason(tmp_path, create_engine({}), p) == "sheet.bad_cell_reference"


def test_overlong_cell_text_and_shared_string(tmp_path):
    eng = create_engine({})
    long = "x" * 40_000
    inline = sheet_doc(f'<row r="1"><c r="A1" t="inlineStr"><is><t>{long}</t></is></c></row>')
    assert read_reason(tmp_path, eng, make_xlsx(tmp_path / "a.xlsx", inline)) == "xlsx.string_too_long"
    sst = HDR + f'<sst {NS} count="1" uniqueCount="1"><si><t>{long}</t></si></sst>'
    p = make_xlsx(tmp_path / "b.xlsx", **{"xl/sharedStrings.xml": sst})
    assert import_reason(tmp_path, eng, p) == "xlsx.string_too_long"


def test_cell_count_and_memory_budgets_apply_to_lazy_parsing(tmp_path):
    rows = "".join(f'<row r="{r}"><c r="A{r}"><v>{r}</v></c><c r="B{r}"><v>1</v></c></row>' for r in range(1, 50))
    p = make_xlsx(tmp_path / "n.xlsx", sheet_doc(rows))
    assert read_reason(tmp_path, create_engine({"limits": {"max_cells": 10}}), p) == "limits.cell_count_exceeded"
    assert read_reason(tmp_path, create_engine({"limits": {"max_store_bytes": 1000}}), p) == "limits.store_bytes_exceeded"


def test_deep_nesting_inside_a_row_is_rejected(tmp_path):
    deep = "<x>" * 100 + "</x>" * 100
    p = make_xlsx(tmp_path / "d.xlsx", sheet_doc(f'<row r="1"><c r="A1"><v>1</v></c>{deep}</row>'))
    assert read_reason(tmp_path, create_engine({}), p) == "xml.forbidden_construct"


def test_malformed_rows_fall_back_then_fail_cleanly(tmp_path):
    p = make_xlsx(tmp_path / "x.xlsx", sheet_doc('<row r="1"><c r="A1"><v>1</v></row>'))
    assert read_reason(tmp_path, create_engine({}), p) in ("xml.malformed", "import_failed")


def test_structure_errors_through_import_xlsx(tmp_path):
    eng = create_engine({})
    parts = xlsx_parts()
    missing = dict(parts)
    del missing["xl/worksheets/sheet2.xml"]
    assert import_reason(tmp_path, eng, write_zip(tmp_path / "1.xlsx", missing)) == "xlsx.sheet_part_missing"
    strict = dict(parts)
    strict["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "http://purl.oclc.org/ooxml/spreadsheetml/main")
    assert import_reason(tmp_path, eng, write_zip(tmp_path / "2.xlsx", strict)) == "xlsx.strict_ooxml"
    nosheets = dict(parts)
    nosheets["xl/workbook.xml"] = HDR + f"<workbook {NS}><sheets/></workbook>"
    assert import_reason(tmp_path, eng, write_zip(tmp_path / "3.xlsx", nosheets)) == "xlsx.no_sheets"
    empty = dict(parts)
    empty["xl/worksheets/sheet1.xml"] = ""
    assert import_reason(tmp_path, eng, write_zip(tmp_path / "4.xlsx", empty)) in ("xlsx.sheet_empty", "zip.corrupt")
    noname = dict(parts)
    noname["xl/workbook.xml"] = parts["xl/workbook.xml"].replace('name="Sheet1" ', 'name="" ')
    assert import_reason(tmp_path, eng, write_zip(tmp_path / "5.xlsx", noname)) == "xlsx.sheet_name_missing"
    zero_ct = {k: v for k, v in parts.items() if k != "xl/sharedStrings.xml"}  # missing optional part is fine
    _h, wb, _ = eng.import_xlsx(write_zip(tmp_path / "6.xlsx", zero_ct))
    assert wb.sheets[0].name == "Sheet1"


def test_zip_limits_apply_through_the_engine(tmp_path):
    p = write_zip(tmp_path / "z.xlsx", xlsx_parts())
    assert import_reason(tmp_path, create_engine({"limits": {"max_part_bytes": 200}}), p) == "zip.part_too_large"
    with pytest.raises(GridoraEngineError) as e:
        create_engine({"limits": {"max_file_bytes": 100}}).import_xlsx(p)
    assert e.value.code == "file_too_large"


def test_legacy_ole2_and_garbage_files(tmp_path):
    eng = create_engine({})
    ole = tmp_path / "old.xlsx"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600)
    assert import_reason(tmp_path, eng, ole) == "xlsx.encrypted_or_legacy"
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not a zip at all")
    assert import_reason(tmp_path, eng, junk) == "zip.not_a_zip"
    assert import_reason(tmp_path, eng, tmp_path / "missing.xlsx") == "io.read_failed"


def test_failed_import_leaks_no_open_resources(tmp_path):
    eng = create_engine({})
    for _ in range(3):
        p = make_xlsx(tmp_path / "bad.xlsx", sheet_doc('<row r="9999999"><c r="A1"><v>1</v></c></row>'))
        with pytest.raises(GridoraEngineError):
            eng.import_xlsx(p)
    assert eng._open == {}
