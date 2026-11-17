"""import_xlsx: package safety -> workbook structure -> lazy sheets -> compatibility report."""
from __future__ import annotations

import re
import uuid
from array import array
from pathlib import Path

from gridora_contracts.models import DefinedName, Frozen

from ..compat.report import Hit, build_report
from ..errors import GridoraEngineError, import_failed, unsupported_workbook
from ..limits import Deadline, ResourceLimits
from ..model.sheet import SheetStore, StoreBudget
from ..model.workbook import SheetState, StyleInfo, WorkbookState
from ..package.parts import PackageModel, resolve_target
from .cellparse import Findings, SheetCtx
from .lazysheet import LazySheet
from .sheetsource import SheetSource, spool_and_scan
from .workbookxml import SheetRef, parse_shared_strings, parse_styles, parse_workbook

MAX_SHEETS = 500
_PART_FEATURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("xlsx.vba_project", re.compile(r"^xl/vbaProject\.bin$", re.IGNORECASE)),
    ("xlsx.pivot_table", re.compile(r"^xl/pivotTables/pivotTable\d+\.xml$", re.IGNORECASE)),
    ("xlsx.chart", re.compile(r"^xl/charts/(chart|chartEx)\d+\.xml$", re.IGNORECASE)),
    ("xlsx.drawing", re.compile(r"^xl/drawings/drawing\d+\.xml$", re.IGNORECASE)),
    ("xlsx.image", re.compile(r"^xl/media/[^/]+$", re.IGNORECASE)),
    ("xlsx.external_link", re.compile(r"^xl/externalLinks/externalLink\d+\.xml$", re.IGNORECASE)),
    ("xlsx.custom_xml", re.compile(r"^customXml/item\d+\.xml$", re.IGNORECASE)),
    ("xlsx.comments", re.compile(r"^xl/comments\d*\.xml$", re.IGNORECASE)),
    ("xlsx.threaded_comments", re.compile(r"^xl/threadedComments/[^/]+\.xml$", re.IGNORECASE)),
    ("xlsx.table", re.compile(r"^xl/tables/table\d+\.xml$", re.IGNORECASE)),
    ("xlsx.slicer", re.compile(r"^xl/slicers/slicer\d+\.xml$", re.IGNORECASE)),
    ("xlsx.connections", re.compile(r"^xl/(connections\.xml|queryTables/[^/]+\.xml)$", re.IGNORECASE)),
    ("xlsx.embedded_object", re.compile(r"^xl/embeddings/[^/]+$", re.IGNORECASE)),
)
_SHEET_CHILD_FEATURES = {
    "mergeCells": "xlsx.merged_cells", "conditionalFormatting": "xlsx.conditional_format",
    "dataValidations": "xlsx.data_validation", "autoFilter": "xlsx.auto_filter",
    "hyperlinks": "xlsx.hyperlinks", "extLst": "xlsx.ext_list", "sheetProtection": "xlsx.sheet_protection",
}


def _add(hits: dict[str, Hit], code: str, n: int = 1, where: str | None = None) -> None:
    h = hits.setdefault(code, Hit(0, []))
    h.count += n
    if where and len(h.locations) < 50:
        h.locations.append(where)


def import_xlsx_file(
    path: Path, limits: ResourceLimits, file_id: str | None
) -> WorkbookState:
    deadline = Deadline(limits.deadline_seconds)
    model = PackageModel.open(path, limits, deadline)
    try:
        state = _build(model, path, limits, deadline, file_id or "")
    except BaseException:
        model.close()
        raise
    state.package = model
    return state


def _build(
    model: PackageModel, path: Path, limits: ResourceLimits, deadline: Deadline, file_id: str
) -> WorkbookState:
    info = parse_workbook(model.read(model.workbook_part), limits, deadline)
    if info.strict:
        raise unsupported_workbook(
            "xlsx.strict_ooxml", "Strict OOXML workbooks are not supported; save as a normal .xlsx."
        )
    if len(info.sheets) > MAX_SHEETS:
        raise unsupported_workbook("xlsx.too_many_sheets", "The workbook has too many sheets.")
    rels = {r.id: r for r in model.relationships(model.workbook_part) if not r.external}
    hits: dict[str, Hit] = {}

    def part_of(type_suffix: str) -> str | None:
        for r in rels.values():
            if r.type.rsplit("/", 1)[-1] == type_suffix:
                return model.actual_name(resolve_target(model.workbook_part, r.target))
        return None

    styles = StyleInfo()
    sp = part_of("styles")
    if sp:
        styles = parse_styles(model.read(sp), limits, deadline)
    sst: list[str] = []
    rich = 0
    ssp = part_of("sharedStrings")
    if ssp:
        sst, rich = parse_shared_strings(model.read(ssp), limits, deadline)
    sst_cache: array[int] = array("i", [-1]) * len(sst)

    budget = StoreBudget(limits.max_store_bytes, limits.max_cells)
    state = WorkbookState(id=str(uuid.uuid4()), file_id=file_id, name=path.stem, budget=budget)
    state.styles = styles
    state.date_system = "1904" if info.date1904 else "1900"
    sheet_ids: dict[int, str] = {}  # position in workbook.xml -> our sheet id

    for pos, ref in enumerate(info.sheets):
        if not ref.name:
            raise import_failed("xlsx.sheet_name_missing", "A sheet has no name.")
        rel = rels.get(ref.rid)
        if rel is None:
            raise import_failed("xlsx.sheet_part_missing", "A sheet points to a missing part.")
        if rel.type.rsplit("/", 1)[-1] != "worksheet":
            _add(hits, "xlsx.chartsheet", 1, ref.name)
            continue
        part = model.actual_name(resolve_target(model.workbook_part, rel.target))
        if part is None:
            raise import_failed("xlsx.sheet_part_missing", "A sheet points to a missing part.")
        state.sheets.append(_load_sheet(model, state, ref, part, sst, sst_cache, limits, deadline, hits))
        sheet_ids[pos] = state.sheets[-1].id
    if not state.sheets:
        raise unsupported_workbook("xlsx.no_worksheets", "The workbook has no worksheets.")

    for dn in info.defined_names:
        if not dn.name or dn.name.startswith("_xlnm._FilterDatabase"):
            continue
        scope = sheet_ids.get(dn.local_sheet_index, "workbook") if dn.local_sheet_index is not None else "workbook"
        state.defined_names.append(DefinedName(name=dn.name, scope=scope, ref=dn.ref))
        _add(hits, "xlsx.defined_name")
    if info.workbook_protection:
        _add(hits, "xlsx.workbook_protection")
    if info.full_calc_on_load:
        _add(hits, "xlsx.full_calc_on_load")
    if info.external_refs:
        _add(hits, "xlsx.external_link", 0)  # counted from parts below; keeps the entry if parts are missing
    for pt in model.parts:
        for code, rx in _PART_FEATURES:
            if rx.match(pt.name):
                _add(hits, code, 1, pt.name)
    if "xlsx.external_link" in hits and hits["xlsx.external_link"].count == 0:
        hits["xlsx.external_link"].count = info.external_refs
    if rich:
        _add(hits, "xlsx.rich_text", rich)
    if not hits.get("xlsx.pivot_table") and any(
        re.match(r"^xl/pivotCache/", p.name, re.IGNORECASE) for p in model.parts
    ):
        _add(hits, "xlsx.pivot_table", 1, "xl/pivotCache")
    state.compat = build_report("import", hits)
    return state


def _load_sheet(
    model: PackageModel, state: WorkbookState, ref: SheetRef, part: str, sst: list[str],
    sst_cache: array[int], limits: ResourceLimits, deadline: Deadline, hits: dict[str, Hit],
) -> SheetState:
    src: SheetSource = spool_and_scan(model.zin, part, limits, deadline)
    findings = Findings()
    state.findings.append(findings)
    store = SheetStore(state.budget)
    ctx = SheetCtx(ref.name, store, state.strings, sst, sst_cache, limits, findings)
    lazy = LazySheet(src, ctx, limits.deadline_seconds)
    sheet = SheetState(
        id=str(uuid.uuid4()), name=ref.name, index=len(state.sheets), store=store,
        visible=ref.state, lazy=lazy, part_name=part, formulas=ctx.formulas, fkind=ctx.fkind, array_ranges=ctx.array_ranges,
    )
    try:
        if lazy.eager:
            lazy.materialize_all()
            _add(hits, "xlsx.lazy_fallback", 1, ref.name)
    except GridoraEngineError:
        lazy.close()
        raise
    lazy.bind(sheet)
    rows_hint, cols_hint = lazy.used_hint()
    if cols_hint == 0 and rows_hint > 0:  # no spans or dimension: read the first block for a width
        lazy.ensure(0, 256)
    f = src.features
    sheet.rtl = f.rtl
    if f.frozen_rows or f.frozen_cols:
        sheet.frozen = Frozen(rows=f.frozen_rows, cols=f.frozen_cols)
        _add(hits, "xlsx.frozen_panes", 1, ref.name)
    if f.rtl:
        _add(hits, "xlsx.rtl_view", 1, ref.name)
    for child, code in _SHEET_CHILD_FEATURES.items():
        n = f.children.get(child, 0)
        if not n:
            continue
        if child == "mergeCells":
            n = max(f.merge_cells, 1)
        elif child == "conditionalFormatting":
            n = f.conditional_formats
        elif child == "dataValidations":
            n = max(f.data_validations, 1)
        elif child == "extLst":
            n = max(len(f.ext_uris), 1)
        elif child == "sheetProtection" and not f.protected:
            continue
        _add(hits, code, n, ref.name)
    _add(hits, "xlsx.formulas_not_recalculated", src.formula_count, ref.name if src.formula_count else None)
    _add(hits, "xlsx.shared_formula", src.shared_count, ref.name if src.shared_count else None)
    _add(hits, "xlsx.array_formula", src.array_count, ref.name if src.array_count else None)
    _add(hits, "xlsx.dynamic_array", src.metadata_count, ref.name if src.metadata_count else None)
    return sheet
