"""Which PRESERVED parts reference cells that were edited (DESIGN.md 5.4).

Only tables, pivot-cache sources and chart series are assessed (small, tested extractors); everything
else that can go stale is reported as "not assessed" rather than silently ignored.
"""
from __future__ import annotations

import re

from ..compat.report import Hit
from ..model.workbook import WorkbookState
from ..package.parts import PackageModel
from .cellparse import parse_ref

_MAX_PART = 8 << 20
_TABLE_REF = re.compile(rb'<(?:\w+:)?table\b[^>]*?\bref="([^"]+)"')
_PIVOT_SRC = re.compile(rb"<(?:\w+:)?worksheetSource\b([^>]*)>")
_ATTR = re.compile(rb'(\w+)="([^"]*)"')
_CHART_F = re.compile(rb"<(?:\w+:)?f>([^<]+)</(?:\w+:)?f>")
_SHEET_REF = re.compile(
    r"(?:'((?:[^']|'')+)'|([^'!,()]+))!\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?"
)
Box = tuple[int, int, int, int]  # r0, c0, r1, c1
Edits = tuple[list[tuple[int, int]], list[Box]]  # edited cells, bulk-written rectangles


def _box(a: str, b: str | None) -> Box | None:
    try:
        r0, c0 = parse_ref(a)
        r1, c1 = parse_ref(b or a)
    except (ValueError, OverflowError):
        return None
    return min(r0, r1), min(c0, c1), max(r0, r1), max(c0, c1)


def _hit(edits: Edits, box: Box) -> bool:
    cells, rects = edits
    r0, c0, r1, c1 = box
    if any(r0 <= r <= r1 and c0 <= c <= c1 for r, c in cells):
        return True
    return any(not (b < r0 or a > r1 or y < c0 or x > c1) for a, x, b, y in rects)


def assess(model: PackageModel, state: WorkbookState) -> dict[str, Hit]:
    edits: dict[str, Edits] = {}
    for s in state.sheets:
        if s.dirty or s.bulk_rects:
            edits[s.name] = ([(k >> 14, k & 0x3FFF) for k in s.dirty], list(s.bulk_rects))
    hits: dict[str, Hit] = {}
    if not edits:
        return hits

    def add(code: str, where: str) -> None:
        h = hits.setdefault(code, Hit(0, []))
        h.count += 1
        if len(h.locations) < 50:
            h.locations.append(where)

    def read(name: str) -> bytes | None:
        part = model.by_name.get(name)
        if part is None or model.zin.by_name[name].file_size > _MAX_PART:
            return None
        return model.read(name)

    for s in state.sheets:  # tables: found through the sheet's relationships
        if s.name not in edits:
            continue
        for rel in model.relationships(s.part_name):
            if rel.external or rel.type.rsplit("/", 1)[-1] != "table":
                continue
            from ..package.parts import resolve_target

            tp = model.actual_name(resolve_target(s.part_name, rel.target))
            data = read(tp) if tp else None
            m = _TABLE_REF.search(data) if data else None
            if m:
                a, _, b = m.group(1).decode().partition(":")
                box = _box(a, b or None)
                if box and _hit(edits[s.name], box):
                    add("xlsx.table.edited_inside", f"{s.name}!{m.group(1).decode()}")
    unassessed = 0
    for name in model.by_name:
        low = name.lower()
        if low.startswith("xl/pivotcache/pivotcachedefinition") and low.endswith(".xml"):
            data = read(name) or b""
            m = _PIVOT_SRC.search(data)
            attrs = {k.decode(): v.decode() for k, v in _ATTR.findall(m.group(1))} if m else {}
            if "ref" in attrs and attrs.get("sheet") in edits:
                a, _, b = attrs["ref"].partition(":")
                box = _box(a, b or None)
                if box and _hit(edits[attrs["sheet"]], box):
                    add("xlsx.pivot_table.source_edited", f"{attrs['sheet']}!{attrs['ref']}")
            elif m and ("name" in attrs or "sheet" not in attrs):
                unassessed += 1  # source given by a named range/table, or not a worksheet
        elif re.match(r"xl/charts/chart\d+\.xml$", low):
            data = read(name) or b""
            for f in _CHART_F.findall(data):
                for m2 in _SHEET_REF.finditer(f.decode("utf-8", "replace")):
                    sheet = (m2.group(1) or m2.group(2)).replace("''", "'")
                    box = _box(f"{m2.group(3)}{m2.group(4)}", f"{m2.group(5)}{m2.group(6)}" if m2.group(5) else None)
                    if box and sheet in edits and _hit(edits[sheet], box):
                        add("xlsx.chart.source_edited", name)
                        break
                else:
                    continue
                break
    if unassessed:
        hits["xlsx.preserved_parts_not_assessed"] = Hit(unassessed, [])
    return hits
