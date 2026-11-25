"""workbook.xml, styles.xml and sharedStrings.xml readers (streaming, hostile-safe)."""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from typing import Literal

from ..errors import import_failed
from ..limits import Deadline, ResourceLimits
from ..model.dates import is_date_format
from ..model.workbook import StyleInfo
from ..package import xmlsafe
from ..package.xmlsafe import local
from .styles import BUILTIN_CODES, read_book

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STRICT_MAIN_NS = "http://purl.oclc.org/ooxml/spreadsheetml/main"


@dataclass
class SheetRef:
    name: str
    sheet_id: str
    rid: str
    state: Literal["visible", "hidden", "very_hidden"]


@dataclass
class DefinedNameInfo:
    name: str
    local_sheet_index: int | None
    ref: str
    hidden: bool = False


@dataclass
class WorkbookInfo:
    sheets: list[SheetRef] = field(default_factory=list)
    defined_names: list[DefinedNameInfo] = field(default_factory=list)
    date1904: bool = False
    external_refs: int = 0
    workbook_protection: bool = False
    full_calc_on_load: bool = False
    strict: bool = False


def parse_workbook(data: bytes, limits: ResourceLimits, deadline: Deadline) -> WorkbookInfo:
    info = WorkbookInfo()
    cur_name: list[str] = []
    cur: dict[str, str] = {}
    in_dn = False

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal in_dn
        ns, _, ln = name.rpartition(" ")
        if ns == STRICT_MAIN_NS:
            info.strict = True
        if ln == "sheet":
            rid = attrs.get(f"{R_NS} id") or attrs.get("id", "")
            st = attrs.get("state", "visible")
            info.sheets.append(
                SheetRef(
                    attrs.get("name", ""), attrs.get("sheetId", ""), rid,
                    "very_hidden" if st == "veryHidden" else "hidden" if st == "hidden" else "visible",
                )
            )
        elif ln == "workbookPr":
            info.date1904 = attrs.get("date1904", "0") in ("1", "true")
        elif ln == "definedName":
            in_dn = True
            cur_name.clear()
            cur.clear()
            cur.update(attrs)
        elif ln == "externalReference":
            info.external_refs += 1
        elif ln == "workbookProtection":
            info.workbook_protection = True
        elif ln == "calcPr":
            info.full_calc_on_load = attrs.get("fullCalcOnLoad", "0") in ("1", "true")

    def end(name: str) -> None:
        nonlocal in_dn
        if local(name) == "definedName" and in_dn:
            in_dn = False
            ls = cur.get("localSheetId")
            info.defined_names.append(
                DefinedNameInfo(
                    cur.get("name", ""), int(ls) if ls and ls.isdigit() else None,
                    "".join(cur_name), cur.get("hidden", "0") in ("1", "true"),
                )
            )

    def chars(text: str) -> None:
        if in_dn:
            cur_name.append(text)

    xmlsafe.parse(data, start=start, end=end, chars=chars, max_depth=limits.max_xml_depth, deadline=deadline)
    if not info.sheets:
        raise import_failed("xlsx.no_sheets", "The workbook contains no sheets.")
    return info


def parse_styles(data: bytes, limits: ResourceLimits, deadline: Deadline) -> StyleInfo:
    codes: dict[int, str] = {}
    table = StyleInfo()
    in_xfs = False

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal in_xfs
        ln = local(name)
        if ln == "numFmt" and "numFmtId" in attrs:
            try:
                codes[int(attrs["numFmtId"])] = attrs.get("formatCode", "")
            except ValueError:
                pass
        elif ln == "cellXfs":
            in_xfs = True
        elif ln == "xf" and in_xfs:
            try:
                fid = int(attrs.get("numFmtId", "0"))
            except ValueError:
                fid = 0
            table.xf_numfmt.append(fid)
            table.xf_is_date.append(is_date_format(codes.get(fid), fid))
            code = codes.get(fid) or BUILTIN_CODES.get(fid)
            table.xf_code.append(None if code in (None, "", "General") else code)

    def end(name: str) -> None:
        nonlocal in_xfs
        if local(name) == "cellXfs":
            in_xfs = False

    xmlsafe.parse(data, start=start, end=end, max_depth=limits.max_xml_depth, deadline=deadline)
    if len(table.xf_numfmt) > 65535:
        raise import_failed("xlsx.too_many_styles", "The workbook has too many cell formats.")
    table.n_imported = len(table.xf_numfmt)
    table.codes = dict(codes)
    try:
        read_book(data, table)
    except Exception:  # noqa: BLE001 - an unusual layout: formats stay readable for display but cannot be changed
        table.props = None
    return table


def parse_shared_strings(
    data: bytes, limits: ResourceLimits, deadline: Deadline
) -> tuple[list[str], int]:
    """Returns (strings, rich_text_count). Rich text runs are joined; phonetic runs skipped."""
    out: list[str] = []
    buf: list[str] = []
    rich = 0
    in_si = in_t = in_rph = has_run = False
    total_chars = 0

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal in_si, in_t, in_rph, has_run
        ln = local(name)
        if ln == "si":
            in_si, has_run = True, False
            buf.clear()
        elif ln == "r" and in_si and not in_rph:
            has_run = True
        elif ln == "rPh":
            in_rph = True
        elif ln == "t" and in_si and not in_rph:
            in_t = True

    def end(name: str) -> None:
        nonlocal in_si, in_t, in_rph, rich, total_chars
        ln = local(name)
        if ln == "t":
            in_t = False
        elif ln == "rPh":
            in_rph = False
        elif ln == "si":
            s = "".join(buf)
            if len(s) > limits.max_field_chars:
                raise import_failed("xlsx.string_too_long", "A shared string is longer than 32,767 characters.")
            total_chars += len(s)
            if total_chars > limits.max_uncompressed_bytes:
                raise import_failed("xlsx.strings_too_large", "The shared strings are too large.")
            if has_run:
                rich += 1
            out.append(s)
            in_si = False

    def chars(text: str) -> None:
        if in_t:
            buf.append(text)

    xmlsafe.parse(data, start=start, end=end, chars=chars, max_depth=limits.max_xml_depth, deadline=deadline)
    return out, rich


def new_id_cache(n: int) -> array[int]:
    return array("i", [-1]) * n
