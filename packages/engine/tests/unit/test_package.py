from __future__ import annotations

import zipfile

import pytest
from support import HDR, PKG_REL, R, read_parts, write_zip, xlsx_parts

from gridora_engine.errors import GridoraEngineError
from gridora_engine.limits import ResourceLimits
from gridora_engine.package.parts import PackageModel, rels_name_for, resolve_target
from gridora_engine.package.zipout import write_package

LIM = ResourceLimits()


def reason(path):
    with pytest.raises(GridoraEngineError) as e:
        PackageModel.open(path, LIM).close()
    return e.value.reason


def test_open_plain_and_macro_enabled(tmp_path):
    with PackageModel.open(write_zip(tmp_path / "a.xlsx", xlsx_parts()), LIM) as m:
        assert m.kind == "xlsx" and m.workbook_part == "xl/workbook.xml"
        assert m.content_types.of("xl/worksheets/sheet1.xml").endswith("worksheet+xml")
        assert m.content_types.of("xl/media/image1.xml") == "application/xml"  # default by extension
    with PackageModel.open(write_zip(tmp_path / "b.xlsx", xlsx_parts(extras=True)), LIM) as m:
        assert m.kind == "xlsm"
        assert m.content_types.of("xl/vbaProject.bin") == "application/vnd.ms-office.vbaProject"


def test_relationships_and_external_targets_are_recorded_not_followed(tmp_path):
    with PackageModel.open(write_zip(tmp_path / "e.xlsx", xlsx_parts(extras=True)), LIM) as m:
        rels = {r.id: r for r in m.relationships("xl/worksheets/sheet1.xml")}
        assert rels["rId1"].external is False and rels["rId2"].external is True
        assert rels["rId2"].target.startswith("https://")
        assert m.relationships("customXml/item1.xml") == []  # no .rels part


def test_path_helpers():
    assert rels_name_for("xl/workbook.xml") == "xl/_rels/workbook.xml.rels"
    assert rels_name_for("a.xml") == "_rels/a.xml.rels"
    assert resolve_target("xl/workbook.xml", "worksheets/sheet1.xml") == "xl/worksheets/sheet1.xml"
    assert resolve_target("xl/worksheets/sheet1.xml", "../drawings/d.xml") == "xl/drawings/d.xml"
    assert resolve_target("xl/workbook.xml", "/docProps/app.xml") == "docProps/app.xml"
    assert resolve_target("", "xl/workbook.xml") == "xl/workbook.xml"
    for bad in ("../../x", "../x", "/../x"):
        with pytest.raises(GridoraEngineError):
            resolve_target("xl/workbook.xml" if bad != "../x" else "a.xml", bad)


def test_structure_errors(tmp_path):
    p = xlsx_parts()
    no_ct = {k: v for k, v in p.items() if k != "[Content_Types].xml"}
    assert reason(write_zip(tmp_path / "1.xlsx", no_ct)) == "package.no_content_types"
    no_root = {k: v for k, v in p.items() if k != "_rels/.rels"}
    assert reason(write_zip(tmp_path / "2.xlsx", no_root)) == "package.no_main_document"
    docx = dict(p)
    docx["[Content_Types].xml"] = p["[Content_Types].xml"].replace("spreadsheetml.sheet.main", "wordprocessingml.document.main")
    assert reason(write_zip(tmp_path / "3.xlsx", docx)) == "package.not_a_workbook"
    escape = dict(p)
    escape["_rels/.rels"] = HDR + f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="../../x.xml"/></Relationships>'
    assert reason(write_zip(tmp_path / "4.xlsx", escape)) == "package.relationship_escape"
    missing = dict(p)
    del missing["xl/workbook.xml"]
    assert reason(write_zip(tmp_path / "5.xlsx", missing)) == "package.no_main_document"
    hostile = dict(p)
    hostile["[Content_Types].xml"] = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Types>&e;</Types>'
    assert reason(write_zip(tmp_path / "6.xlsx", hostile)) == "xml.forbidden_construct"


@pytest.mark.parametrize("extras", [False, True])
def test_noop_roundtrip_is_byte_equal_per_part_and_keeps_order(tmp_path, extras):
    src = write_zip(tmp_path / "in.xlsx", xlsx_parts(extras))
    out = tmp_path / "out.xlsx"
    with PackageModel.open(src, LIM) as m:
        write_package(m, out)
    a, b = read_parts(src), read_parts(out)
    assert list(a) == list(b)  # same parts, same order
    assert all(a[n] == b[n] for n in a)  # byte-equal decompressed content
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
    assert not (tmp_path / "out.xlsx.part").exists()


def test_only_dirty_parts_change_and_dropped_parts_disappear(tmp_path):
    src = write_zip(tmp_path / "in.xlsx", xlsx_parts(extras=True))
    out = tmp_path / "out.xlsx"
    with PackageModel.open(src, LIM) as m:
        sheet = m.by_name["xl/worksheets/sheet2.xml"]
        sheet.data, sheet.state = b"<changed/>", "dirty"
        m.by_name["customXml/item1.xml"].state = "dropped"
        write_package(m, out)
    a, b = read_parts(src), read_parts(out)
    assert "customXml/item1.xml" not in b and b["xl/worksheets/sheet2.xml"] == b"<changed/>"
    assert all(a[n] == b[n] for n in b if n != "xl/worksheets/sheet2.xml")
    assert [n for n in a if n in b] == list(b)


def test_budget_still_applies_while_writing(tmp_path):
    src = write_zip(tmp_path / "in.xlsx", xlsx_parts())
    with PackageModel.open(src, ResourceLimits(max_uncompressed_bytes=20_000)) as m:
        m.zin.total_read = 19_999
        with pytest.raises(GridoraEngineError) as e:
            write_package(m, tmp_path / "out.xlsx")
    assert e.value.reason == "zip.uncompressed_too_large"
    assert not (tmp_path / "out.xlsx").exists() and not (tmp_path / "out.xlsx.part").exists()
