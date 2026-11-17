"""A new XLSX package from a workbook that has no source package (imported from CSV)."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..errors import validation_failed
from ..model.sheet import CHUNK_ROWS
from ..model.values import STR
from ..model.workbook import SheetState, WorkbookState
from ..package.parts import Part
from ..package.zipout import write_parts
from .rowpatch import cell_xml
from .textenc import col_letters, xml_escape

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_BAD_NAME = re.compile(r"[\\/?*\[\]:]")


def _sheet_chunks(sheet: SheetState, state: WorkbookState) -> Iterator[bytes]:
    rows, cols = sheet.store.used_size()
    dim = f"A1:{col_letters(cols - 1)}{rows}" if rows and cols else "A1"
    views = '<sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews>' if sheet.rtl else ""
    yield f'{HDR}<worksheet {NS}><dimension ref="{dim}"/>{views}<sheetData>'.encode()
    for first, chunks in sheet.store.row_blocks(cols):
        out: list[bytes] = []
        for r in range(first, min(first + CHUNK_ROWS, rows)):
            i = r - first
            cells = []
            for c, ch in enumerate(chunks):
                if ch is None:
                    continue
                x = cell_xml(r, c, ch.tags[i], ch.vals[i], ch.styles[i], sheet.formulas.get((r << 14) | c), state.strings)
                if x is not None:
                    cells.append(x)
            if cells:
                out.append(f'<row r="{r + 1}">'.encode() + b"".join(cells) + b"</row>")
        yield b"".join(out)
    yield b"</sheetData></worksheet>"


def write_new_package(state: WorkbookState, path: Path) -> int:
    """Write the workbook as a new .xlsx; returns the number of text cells (written inline)."""
    for s in state.sheets:
        if not s.name or len(s.name) > 31 or _BAD_NAME.search(s.name):
            raise validation_failed("export.bad_sheet_name", "A sheet name is not valid in an Excel workbook.")
    n = len(state.sheets)
    ct = (HDR + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n))
          + "</Types>")
    root = HDR + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    wb = HDR + f"<workbook {NS}><workbookPr/><sheets>" + "".join(
        f'<sheet name="{xml_escape(s.name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(state.sheets)) + "</sheets></workbook>"
    wbrels = HDR + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
        f'<Relationship Id="rId{i + 1}" Type="{REL}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n)
    ) + f'<Relationship Id="rId{n + 1}" Type="{REL}/styles" Target="styles.xml"/></Relationships>'
    styles = (HDR + f"<styleSheet {NS}><fonts count=\"1\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    parts = [Part("[Content_Types].xml", "added", ct.encode()), Part("_rels/.rels", "added", root.encode()),
             Part("xl/workbook.xml", "added", wb.encode()), Part("xl/_rels/workbook.xml.rels", "added", wbrels.encode()),
             Part("xl/styles.xml", "added", styles.encode())]
    text_cells = 0
    for i, s in enumerate(state.sheets):
        p = Part(f"xl/worksheets/sheet{i + 1}.xml", "added")
        p.producer = (lambda s=s: _sheet_chunks(s, state))
        parts.append(p)
        _rows, cols = s.store.used_size()
        for _f, chunks in s.store.row_blocks(cols):
            text_cells += sum(1 for ch in chunks if ch is not None for t in ch.tags if t == STR)
    write_parts(None, parts, path)
    return text_cells
