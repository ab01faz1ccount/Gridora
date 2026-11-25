"""export_xlsx: patch edited rows into the original package; new package for CSV workbooks."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

from gridora_contracts.models import CompatibilityReport

from ..compat.report import Hit, build_report
from ..errors import unsupported_workbook
from ..formula.parser import Func, walk
from ..limits import ResourceLimits
from ..model.workbook import SheetState, WorkbookState
from ..package.parts import PackageModel, Part, resolve_target
from ..package.zipout import write_parts
from . import risks
from .cellparse import parse_ref
from .newpackage import write_new_package
from .rowpatch import sheet_chunks
from .sheetsource import SheetSource
from .styles import patch_styles
from .textenc import col_letters

_CALCPR = re.compile(rb"<calcPr\b([^>]*?)(/?)>")
_AFTER_CALCPR = re.compile(
    rb"<(?:oleSize|customWorkbookViews|pivotCaches|smartTagPr|smartTagTypes|webPublishing|"
    rb"fileRecoveryPr|webPublishObjects|extLst)\b"
)


def _add(hits: dict[str, Hit], code: str, n: int = 1, where: str | None = None) -> None:
    h = hits.setdefault(code, Hit(0, []))
    h.count += n
    if where and len(h.locations) < 50:
        h.locations.append(where)


def export_xlsx_file(state: WorkbookState, path: Path, limits: ResourceLimits) -> CompatibilityReport:
    hits: dict[str, Hit] = {}
    model = state.package
    if model is None:
        n = write_new_package(state, path)
        _add(hits, "xlsx.generated_from_csv")
        if n:
            _add(hits, "xlsx.inline_strings", n)
        return build_report("export", hits)
    assert isinstance(model, PackageModel)
    parts = [replace(p) for p in model.parts]
    by_name = {p.name: p for p in parts}
    edited = [s for s in state.sheets if s.dirty or s.bulk_rects]
    inline = 0
    for sheet in edited:
        part = by_name[sheet.part_name]
        src = _source_of(sheet)
        part.state = "dirty"
        part.producer = _producer(src, sheet, state)
        inline += _inline_strings(sheet)
    if edited:
        if inline:
            _add(hits, "xlsx.inline_strings", inline)
        formulas_total = sum(_formula_cells(s) for s in state.sheets)
        if formulas_total:
            _formula_findings(state, hits)
            if _set_full_calc(model, parts):
                _add(hits, "xlsx.full_calc_on_load_set")
        if _formulas_changed(edited) and _drop_calc_chain(model, parts):
            _add(hits, "xlsx.calc_chain_dropped")
        for code, h in risks.assess(model, state).items():
            hits[code] = h
    if state.styles is not None and (state.styles.derived or state.styles.new_codes):
        _patch_styles(model, parts, state)
    if model.kind in ("xlsm", "xltm"):
        _add(hits, "xlsx.macro_enabled_extension")
    for fnd in state.findings:
        for code, n in fnd.counts.items():
            _add(hits, code, n)
    write_parts(model, parts, path)
    PackageModel.open(path, limits).close()  # never leave a file our own reader cannot open
    return build_report("export", hits)


_DATE_FUNCS = frozenset({"YEAR", "MONTH", "DAY", "DATE", "EDATE", "EOMONTH", "DATEDIF", "DATEVALUE", "TEXT"})


def _formula_findings(state: WorkbookState, hits: dict[str, Hit]) -> None:
    calc = state.calc
    if calc is None or not calc.built:
        return
    f = calc.findings()
    cannot = set(calc.frozen) | calc.stale
    if cannot:
        _add(hits, "xlsx.cached_values_stale", len(cannot))
        locs = hits["xlsx.cached_values_stale"].locations
        for fk in sorted(cannot):
            name = state.sheets[fk >> 40].name
            if name not in locs and len(locs) < 50:
                locs.append(name)
    if f["counts"].get("unsupported_function"):
        _add(hits, "formula.unsupported_function", f["counts"]["unsupported_function"])
    if f["circular"]:
        _add(hits, "formula.circular", f["circular"])
    if calc.calendar != "gregorian":
        n = sum(1 for ast in calc.asts.values() if any(isinstance(x, Func) and x.name in _DATE_FUNCS for x in walk(ast)))
        if n:
            _add(hits, "formula.calendar_mode", n)


def _source_of(sheet: SheetState) -> SheetSource:
    lazy = sheet.lazy
    src = getattr(lazy, "source", None)
    if lazy is None or src is None or getattr(lazy, "eager", True) or getattr(lazy, "fell_back", True) or not src.indexed:
        raise unsupported_workbook(
            "export.sheet_not_patchable",
            "This sheet's XML layout cannot be patched safely, so edits to it cannot be exported yet.",
        )
    assert isinstance(src, SheetSource)
    return src


def _producer(src: SheetSource, sheet: SheetState, state: WorkbookState) -> Callable[[], Iterator[bytes]]:
    new_dim = _new_dimension(src, sheet)
    return lambda: sheet_chunks(src, sheet, state.strings, new_dim)


def _new_dimension(src: SheetSource, sheet: SheetState) -> str | None:
    """A new <dimension ref> only if edits extend the used range beyond the original one."""
    dim = src.features.dimension
    rows, cols = sheet.store.used_size()
    try:
        a, _, b = dim.partition(":")
        r0, c0 = parse_ref(a)
        r1, c1 = parse_ref(b or a)
    except (ValueError, OverflowError):
        return None
    if rows - 1 <= r1 and cols - 1 <= c1:
        return None
    return f"{col_letters(c0)}{r0 + 1}:{col_letters(max(c1, cols - 1))}{max(r1, rows - 1) + 1}"


def _formula_cells(sheet: SheetState) -> int:
    src = getattr(sheet.lazy, "source", None)
    return max(src.formula_count if src is not None else 0, len(sheet.formulas))


def _inline_strings(sheet: SheetState) -> int:
    """Edited text cells written as inline strings (per-cell edits plus bulk rectangles)."""
    n = 0
    for k in sheet.dirty:
        r, c = k >> 14, k & 0x3FFF
        if k not in sheet.formulas and sheet.store.get(r, c)[0] == 2 and not any(
            a <= r <= b and x <= c <= y for a, x, b, y in sheet.bulk_rects
        ):
            n += 1
    for r0, c0, r1, c1 in sheet.bulk_rects:
        for c in range(c0, c1 + 1):
            tags, _v, _s = sheet.store.column_arrays(c, r0, r1)
            n += tags.count(2)
    return n


def _formulas_changed(edited: list[SheetState]) -> bool:
    for s in edited:
        if s.bulk_formulas_changed:
            return True
        for k in s.dirty:
            if s.orig[k][3] != s.formulas.get(k):
                return True
    return False


def _patch_styles(model: PackageModel, parts: list[Part], state: WorkbookState) -> None:
    """Append the formats made since import to styles.xml (existing entries never change)."""
    name = None
    for r in model.relationships(model.workbook_part):
        if not r.external and r.type.rsplit("/", 1)[-1] == "styles":
            name = model.actual_name(resolve_target(model.workbook_part, r.target))
    if name is None or state.styles is None:
        raise unsupported_workbook("export.styles_not_patchable", "This workbook has no cell format part to extend.")
    part = next(p for p in parts if p.name == name)
    part.data, part.state = patch_styles(model.read(name), state.styles), "dirty"


def _set_full_calc(model: PackageModel, parts: list[Part]) -> bool:
    """Ask Excel to recalculate everything on open (patching only calcPr in workbook.xml)."""
    part = next(p for p in parts if p.name == model.workbook_part)
    data = model.read(part.name)
    m = _CALCPR.search(data)
    if m:
        attrs = m.group(1)
        if b"fullCalcOnLoad" in attrs:
            attrs = re.sub(rb'fullCalcOnLoad="[^"]*"', b'fullCalcOnLoad="1"', attrs)
        else:
            attrs = attrs.rstrip() + b' fullCalcOnLoad="1"' if not attrs.endswith(b" ") else attrs + b'fullCalcOnLoad="1"'
        new = b"<calcPr" + attrs + m.group(2) + b">"
        out = data[: m.start()] + new + data[m.end():]
    else:
        if re.search(rb"<\w+:workbook\b", data):
            return False  # prefixed namespace: not patched
        nxt = _AFTER_CALCPR.search(data)
        pos = nxt.start() if nxt else data.rfind(b"</workbook>")
        if pos < 0:
            return False
        out = data[:pos] + b'<calcPr fullCalcOnLoad="1"/>' + data[pos:]
    part.data, part.state = out, "dirty"
    return True


def _drop_calc_chain(model: PackageModel, parts: list[Part]) -> bool:
    """calcChain lists formula cells; a stale chain makes Excel report corruption, so it is dropped
    together with its relationship and content-type override (Excel rebuilds it)."""
    chain = None
    rels = model.relationships(model.workbook_part)
    for r in rels:
        if not r.external and r.type.rsplit("/", 1)[-1] == "calcChain":
            chain = model.actual_name(resolve_target(model.workbook_part, r.target))
    if chain is None:
        return False
    by_name = {p.name: p for p in parts}
    by_name[chain].state = "dropped"
    from ..package.parts import CONTENT_TYPES, rels_name_for

    rn = rels_name_for(model.workbook_part)
    rp = by_name[model.actual_name(rn) or rn]
    data = model.read(rp.name)
    rp.data, rp.state = re.sub(rb"<Relationship\b[^>]*calcChain[^>]*/>", b"", data), "dirty"
    cp = by_name[CONTENT_TYPES]
    cdata = model.read(CONTENT_TYPES)
    cp.data, cp.state = re.sub(rb"<Override\b[^>]*calcChain[^>]*/>", b"", cdata), "dirty"
    return True
