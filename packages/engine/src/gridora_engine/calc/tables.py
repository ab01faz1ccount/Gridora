"""Table (ListObject) definitions of an imported workbook, for structured references (E7).

Only reads the table parts that exist in the package; tables created inside Gridora are a later
feature. Never raises on odd XML: a table that cannot be understood is simply not defined (its
structured references then evaluate to #REF!)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from ..formula.parser import Err, Ref, StructRef
from ..formula.refs import MAX_COLS, parse_cell
from ..model.workbook import WorkbookState

_ATTR = re.compile(rb'(\w+)="([^"]*)"')
_COLS = re.compile(rb"<(?:\w+:)?tableColumn\b([^>]*?)/?>")
_ROOT = re.compile(rb"<(?:\w+:)?table\b([^>]*)>")
_MAX_PART = 8 * 1024 * 1024


@dataclass(slots=True)
class TableDef:
    name: str
    sheet: int
    r0: int
    c0: int
    r1: int
    c1: int
    header_rows: int
    totals_rows: int
    columns: list[str]


def load_tables(state: WorkbookState) -> dict[str, TableDef]:
    model = getattr(state, "package", None)
    out: dict[str, TableDef] = {}
    if model is None:
        return out
    from ..package.parts import resolve_target

    for si, s in enumerate(state.sheets):
        try:
            rels = list(model.relationships(s.part_name))
        except Exception:  # pragma: no cover - damaged rels: no tables for this sheet
            continue
        for rel in rels:
            if rel.external or rel.type.rsplit("/", 1)[-1] != "table":
                continue
            try:
                tp = model.actual_name(resolve_target(s.part_name, rel.target))
                part = model.by_name.get(tp) if tp else None
                if part is None or model.zin.by_name[tp].file_size > _MAX_PART:
                    continue
                data = model.read(tp)
            except Exception:  # pragma: no cover
                continue
            t = _parse_table(si, data)
            if t is not None:
                out[t.name.lower()] = t
    return out


def _parse_table(si: int, data: bytes) -> TableDef | None:
    m = _ROOT.search(data)
    if not m:
        return None
    a = {k.decode(): html.unescape(v.decode("utf-8", "replace")) for k, v in _ATTR.findall(m.group(1))}
    ref = a.get("ref", "")
    name = a.get("displayName") or a.get("name")
    if not name or ":" not in ref:
        return None
    p0, p1 = (parse_cell(x.replace("$", "")) for x in ref.split(":", 1))
    if not p0 or not p1:
        return None
    cols = []
    for cm in _COLS.finditer(data):
        ca = {k.decode(): html.unescape(v.decode("utf-8", "replace")) for k, v in _ATTR.findall(cm.group(1))}
        cols.append(ca.get("name", ""))
    try:
        header = int(a.get("headerRowCount", "1"))
        totals = int(a.get("totalsRowCount", "0"))
    except ValueError:
        return None
    return TableDef(name, si, p0[0], p0[1], p1[0], p1[1], header, totals, cols)


def resolve_struct(
    node: StructRef, tables: dict[str, TableDef], state: WorkbookState, si: int, row: int, col: int
) -> Ref | Err:
    t: TableDef | None
    if node.table is None:
        t = next((x for x in tables.values() if x.sheet == si and x.r0 <= row <= x.r1 and x.c0 <= col <= x.c1), None)
    else:
        t = tables.get(node.table.lower())
    if t is None:
        return Err("#REF!")
    data0, data1 = t.r0 + t.header_rows, t.r1 - t.totals_rows
    items = set(node.items) or {"DATA"}
    if "THIS_ROW" in items:
        if t.sheet != si or not (data0 <= row <= data1):
            return Err("#VALUE!")
        r0 = r1 = row
    else:
        spans = []
        if "ALL" in items:
            spans.append((t.r0, t.r1))
        if "DATA" in items:
            spans.append((data0, data1))
        if "HEADERS" in items:
            spans.append((t.r0, t.r0 + t.header_rows - 1))
        if "TOTALS" in items:
            spans.append((t.r1 - t.totals_rows + 1, t.r1))
        spans = [(a, b) for a, b in spans if a <= b]
        if not spans:
            return Err("#REF!")
        r0, r1 = min(a for a, _ in spans), max(b for _, b in spans)
    if node.col1 is None:
        c0, c1 = t.c0, t.c1
    else:
        names = [n.lower() for n in t.columns]
        try:
            c0 = t.c0 + names.index(node.col1.lower())
            c1 = c0 if node.col2 is None else t.c0 + names.index(node.col2.lower())
        except ValueError:
            return Err("#REF!")
        if c0 > c1:
            c0, c1 = c1, c0
    return Ref(state.sheets[t.sheet].name, r0, c0, r1, c1)
