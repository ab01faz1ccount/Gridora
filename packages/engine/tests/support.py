"""Test helpers: fixtures are generated from raw XML (provenance: generated here, not by Excel)."""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path

NS = (
    'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
Data = str | bytes


def xlsx_parts(extras: bool = False) -> dict[str, Data]:
    """Parts of a small workbook. extras=True adds parts a reader will not understand."""
    sst = ["name", "qty", "علی", "مریم", "متن برگه ۲"]
    sst_xml = HDR + f'<sst {NS} count="5" uniqueCount="5">' + "".join(
        f"<si><t>{s}</t></si>" for s in sst) + "</sst>"
    styles = HDR + (
        f'<styleSheet {NS}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts>'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '<dxfs count="1"><dxf><font><b/></font></dxf></dxfs></styleSheet>')
    tail = ""
    if extras:
        tail = ('<mergeCells count="1"><mergeCell ref="E1:F1"/></mergeCells>'
                '<conditionalFormatting sqref="B2:B4"><cfRule type="cellIs" dxfId="0" priority="1" operator="greaterThan"><formula>10</formula></cfRule></conditionalFormatting>'
                '<drawing r:id="rId1"/>'
                '<extLst><ext uri="{CUSTOM-EXT-URI}" xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"><x14:marker value="keep-me"/></ext></extLst>')
    rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>5</v></c><c r="C2"><f>B2*2</f><v>10</v></c><c r="D2" s="1"><v>45292</v></c></row>'
            '<row r="3"><c r="A3" t="s"><v>3</v></c><c r="B3"><v>7.5</v></c></row>'
            '<row r="4"><c r="A4" t="b"><v>1</v></c><c r="B4" t="e"><v>#DIV/0!</v></c></row>')
    sheet1 = HDR + (f'<worksheet {NS}><dimension ref="A1:D4"/><sheetViews><sheetView workbookViewId="0"/></sheetViews>'
                    f'<sheetData>{rows}</sheetData>{tail}</worksheet>')
    sheet2 = HDR + (f'<worksheet {NS}><dimension ref="A1:A1"/><sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews>'
                    '<sheetData><row r="1"><c r="A1" t="s"><v>4</v></c></row></sheetData></worksheet>')
    wb = HDR + (f'<workbook {NS}><workbookPr/><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/>'
                '<sheet name="برگه ۲" sheetId="2" r:id="rId2"/></sheets><calcPr calcId="191029"/></workbook>')
    main_ct = ("application/vnd.ms-excel.sheet.macroEnabled.main+xml" if extras else
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
    ws = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    ov = [("/xl/workbook.xml", main_ct), ("/xl/worksheets/sheet1.xml", ws), ("/xl/worksheets/sheet2.xml", ws),
          ("/xl/sharedStrings.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"),
          ("/xl/styles.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")]
    rels = [("rId1", "worksheet", "worksheets/sheet1.xml"), ("rId2", "worksheet", "worksheets/sheet2.xml"),
            ("rId3", "sharedStrings", "sharedStrings.xml"), ("rId4", "styles", "styles.xml")]
    parts: dict[str, Data] = {}
    default = ('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>')
    if extras:
        parts["customXml/item1.xml"] = HDR + '<gridoraProbe xmlns="urn:gridora:probe">custom-xml-payload-\u06cc</gridoraProbe>'
        parts["xl/pivotCache/pivotCacheDefinition1.xml"] = HDR + f'<pivotCacheDefinition {NS} refreshOnLoad="1"/>'
        parts["xl/vbaProject.bin"] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(range(256)) * 8
        parts["xl/drawings/drawing1.xml"] = HDR + '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"/>'
        parts["xl/worksheets/_rels/sheet1.xml.rels"] = HDR + (
            f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{R}/drawing" Target="../drawings/drawing1.xml"/>'
            f'<Relationship Id="rId2" Type="{R}/hyperlink" Target="https://example.invalid/x" TargetMode="External"/></Relationships>')
        rels += [("rId5", "pivotCacheDefinition", "pivotCache/pivotCacheDefinition1.xml"), ("rId6", "vbaProject", "vbaProject.bin")]
        ov += [("/xl/pivotCache/pivotCacheDefinition1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"),
               ("/xl/drawings/drawing1.xml", "application/vnd.openxmlformats-officedocument.drawing+xml")]
        default += '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
    ct = HDR + f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{default}' + "".join(
        f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in ov) + "</Types>"
    wbrels = HDR + f'<Relationships xmlns="{PKG_REL}">' + "".join(
        f'<Relationship Id="{i}" Type="{R}/{t}" Target="{tg}"/>' for i, t, tg in rels) + "</Relationships>"
    root = HDR + f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    ordered: dict[str, Data] = {"[Content_Types].xml": ct, "_rels/.rels": root, "xl/workbook.xml": wb,
                                "xl/_rels/workbook.xml.rels": wbrels, "xl/worksheets/sheet1.xml": sheet1,
                                "xl/worksheets/sheet2.xml": sheet2, "xl/sharedStrings.xml": sst_xml, "xl/styles.xml": styles}
    ordered.update(parts)
    return ordered


def write_zip(path: Path, parts: dict[str, Data], method: int = zipfile.ZIP_DEFLATED,
              stored: set[str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", method) as z:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if stored and name in stored else method
            z.writestr(info, data.encode("utf-8") if isinstance(data, str) else data)
    return path


def read_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist() if not i.filename.endswith("/")}


# -- raw zip surgery (central directory header offsets: flags +8, method +10, usize +24, offset +42)
def central_offset(raw: bytes, name: str) -> int:
    i = 0
    while True:
        i = raw.index(b"PK\x01\x02", i)
        nlen = struct.unpack_from("<H", raw, i + 28)[0]
        if raw[i + 46: i + 46 + nlen] == name.encode():
            return i
        i += 4


def patch(raw: bytes, offset: int, fmt: str, value: int) -> bytes:
    b = bytearray(raw)
    struct.pack_into(fmt, b, offset, value)
    return bytes(b)
