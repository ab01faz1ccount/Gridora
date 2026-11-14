# ruff: noqa  (scratch spike script, not product code)
"""Spike fixtures built from raw XML (provenance: generated here, not by Excel)."""
import zipfile, sys
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

def build(path, extras=True):
    sst = ["name", "qty", "علی", "مریم", "برگه ۲ متن"]
    sst_xml = HDR + f'<sst {NS} count="{len(sst)}" uniqueCount="{len(sst)}">' + "".join(f"<si><t>{s}</t></si>" for s in sst) + "</sst>"
    styles = HDR + f'''<styleSheet {NS}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles><dxfs count="1"><dxf><font><b/></font></dxf></dxfs></styleSheet>'''
    ext = ""
    extra_tail = ""
    if extras:
        extra_tail = ('<mergeCells count="1"><mergeCell ref="E1:F1"/></mergeCells>'
          '<conditionalFormatting sqref="B2:B4"><cfRule type="cellIs" dxfId="0" priority="1" operator="greaterThan"><formula>10</formula></cfRule></conditionalFormatting>'
          '<dataValidations count="1"><dataValidation type="whole" allowBlank="1" showErrorMessage="1" sqref="B2:B4"><formula1>0</formula1><formula2>100</formula2></dataValidation></dataValidations>'
          '<drawing r:id="rId1"/>'
          '<extLst><ext uri="{CUSTOM-EXT-URI}" xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"><x14:marker value="keep-me"/></ext></extLst>')
    rows = ('<row r="1" ht="20" customHeight="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>5</v></c><c r="C2"><f>B2*2</f><v>10</v></c><c r="D2" s="1"><v>45292</v></c></row>'
            '<row r="3"><c r="A3" t="s"><v>3</v></c><c r="B3"><v>7</v></c><c r="C3"><f>B3*2</f><v>14</v></c></row>'
            '<row r="4"><c r="A4"><v>0</v></c><c r="B4"><v>12</v></c><c r="C4"><f>SUM(B2:B4)</f><v>24</v></c><c r="D4"><f>VLOOKUP("x",A1:B4,2,FALSE)</f><v>0</v></c></row>'
            '<row r="5"><c r="A5" t="b"><v>1</v></c><c r="B5" t="e"><v>#DIV/0!</v></c></row>')
    sheet1 = HDR + f'<worksheet {NS}><dimension ref="A1:D5"/><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/><cols><col min="1" max="1" width="18" customWidth="1"/></cols><sheetData>{rows}</sheetData>{extra_tail}</worksheet>'
    sheet2 = HDR + f'<worksheet {NS}><dimension ref="A1:A1"/><sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews><sheetData><row r="1"><c r="A1" t="s"><v>4</v></c></row></sheetData></worksheet>'
    wb = HDR + f'<workbook {NS}><workbookPr/><bookViews><workbookView/></bookViews><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/><sheet name="برگه ۲" sheetId="2" r:id="rId2"/></sheets><definedNames><definedName name="Qty">Sheet1!$B$2:$B$4</definedName></definedNames><calcPr calcId="191029"/></workbook>'
    ct = HDR + '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'''
    wbrels = [("rId1","worksheet","worksheets/sheet1.xml"),("rId2","worksheet","worksheets/sheet2.xml"),("rId3","sharedStrings","sharedStrings.xml"),("rId4","styles","styles.xml")]
    ov = [("/xl/workbook.xml","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
          ("/xl/worksheets/sheet1.xml","application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
          ("/xl/worksheets/sheet2.xml","application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
          ("/xl/sharedStrings.xml","application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"),
          ("/xl/styles.xml","application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")]
    parts = {}
    if extras:
        parts["customXml/item1.xml"] = HDR + '<gridoraProbe xmlns="urn:gridora:probe">custom-xml-payload-\u06cc</gridoraProbe>'
        parts["customXml/_rels/item1.xml.rels"] = HDR + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        parts["xl/pivotCache/pivotCacheDefinition1.xml"] = HDR + f'<pivotCacheDefinition {NS} r:id="rId1" refreshOnLoad="1"><cacheSource type="worksheet"><worksheetSource ref="A1:B4" sheet="Sheet1"/></cacheSource><cacheFields count="1"><cacheField name="name" numFmtId="0"/></cacheFields></pivotCacheDefinition>'
        parts["xl/vbaProject.bin"] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(range(256)) * 4
        parts["xl/drawings/drawing1.xml"] = HDR + '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
        parts["xl/worksheets/_rels/sheet1.xml.rels"] = HDR + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/drawing" Target="../drawings/drawing1.xml"/></Relationships>'
        wbrels += [("rId5","pivotCacheDefinition","pivotCache/pivotCacheDefinition1.xml"),("rId6","vbaProject","vbaProject.bin")]
        ov += [("/xl/pivotCache/pivotCacheDefinition1.xml","application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"),
               ("/xl/drawings/drawing1.xml","application/vnd.openxmlformats-officedocument.drawing+xml"),
               ("/customXml/item1.xml","application/xml")]
        ct = ct.replace("</Types>","") + '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
        ov[0] = ("/xl/workbook.xml","application/vnd.ms-excel.sheet.macroEnabled.main+xml")
    ct += "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in ov) + "</Types>"
    wbrels_xml = HDR + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
        f'<Relationship Id="{i}" Type="{R}/{t}" Target="{tg}"/>' for i, t, tg in wbrels) + "</Relationships>"
    rootrels = HDR + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    parts.update({"[Content_Types].xml": ct, "_rels/.rels": rootrels, "xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": wbrels_xml,
                  "xl/worksheets/sheet1.xml": sheet1, "xl/worksheets/sheet2.xml": sheet2, "xl/sharedStrings.xml": sst_xml, "xl/styles.xml": styles})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", parts.pop("[Content_Types].xml"))
        for n, d in parts.items():
            z.writestr(n, d)

if __name__ == "__main__":
    build("fx/plain.xlsx", extras=False)
    build("fx/extras.xlsx", extras=True)
    print("ok")
