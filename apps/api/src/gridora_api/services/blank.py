# ruff: noqa: E501 (XML literals)
"""A new, empty workbook: one empty sheet, written as a small valid .xlsx so it goes through the same
import path as any uploaded file (nothing special-cased downstream)."""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile

from ..storage.layout import StorageLayout
from .uploads import StoredUpload, clean_display_name

_HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def blank_xlsx(sheet_name: str = "Sheet1", *, rtl: bool = True) -> bytes:
    """Bytes of an .xlsx with a single empty sheet (right-to-left when `rtl`)."""
    name = "".join(ch for ch in sheet_name if ch not in '[]:*?/\\<>&"\'')[:31] or "Sheet1"
    view = '<sheetView rightToLeft="1" workbookViewId="0"/>' if rtl else '<sheetView workbookViewId="0"/>'
    parts = {
        "[Content_Types].xml": _HDR
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>",
        "_rels/.rels": _HDR
        + f'<Relationships xmlns="{_PKG}"><Relationship Id="rId1" Type="{_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": _HDR
        + f'<workbook xmlns="{_MAIN}" xmlns:r="{_R}"><workbookPr/><sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
        '<calcPr calcId="191029"/></workbook>',
        "xl/_rels/workbook.xml.rels": _HDR
        + f'<Relationships xmlns="{_PKG}"><Relationship Id="rId1" Type="{_R}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{_R}/styles" Target="styles.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": _HDR
        + f'<worksheet xmlns="{_MAIN}"><dimension ref="A1"/><sheetViews>{view}</sheetViews><sheetData/></worksheet>',
        "xl/styles.xml": _HDR
        + f'<styleSheet xmlns="{_MAIN}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        "<borders count=\"1\"><border><left/><right/><top/><bottom/><diagonal/></border></borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for part, data in parts.items():
            info = zipfile.ZipInfo(part, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data.encode("utf-8"))
    return buf.getvalue()


def store_blank(layout: StorageLayout, display_name: str, *, rtl: bool = True) -> StoredUpload:
    """Writes the blank workbook into quarantine, like a received upload, ready for `finalize_upload`."""
    base = clean_display_name(display_name)
    if base.lower().endswith((".xlsx", ".xlsm", ".csv")):
        base = base.rsplit(".", 1)[0] or "Book"
    data = blank_xlsx(rtl=rtl)
    qpath = layout.quarantine_path(uuid.uuid4())
    qpath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    qpath.write_bytes(data)
    return StoredUpload(qpath, f"{base}.xlsx", "xlsx", len(data), hashlib.sha256(data).hexdigest())
