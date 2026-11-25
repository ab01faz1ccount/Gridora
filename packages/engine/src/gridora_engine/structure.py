"""Insert and delete rows / columns (optional engine extension, contract v0.8.0).

Scope (deliberately narrow, everything else is REFUSED with `operation_conflict` rather than risking a
silently wrong file): sheets without merged cells, conditional formats, validations, tables, drawings,
comments, hyperlinks, filters or array formulas; workbooks without charts, pivot caches, spilled
(dynamic-array) formulas or defined names pointing at the sheet.

What an operation does, in order: moves the cells of the sheet, rewrites every formula of the workbook
that points into the sheet (Excel's rules, formula.structure), forgets the calculation graph and
recomputes. Undo is the opposite operation plus the data that cannot be derived: the deleted cells and the
old text of formulas whose references were clipped or became #REF!.
"""
from __future__ import annotations

from array import array
from typing import TYPE_CHECKING, Any

from gridora_contracts.models import Cell, SheetStructureDelta
from gridora_contracts.protocols import WorkbookHandle

from .errors import GridoraEngineError, bad_request, too_large_for_history, validation_failed
from .formula.structure import refers_to, shift_formula, transform_index
from .model.cellview import cell_to_internal, read_cell
from .model.edits import apply_all
from .model.sheet import CHUNK_BYTES
from .model.workbook import SheetState, WorkbookState
from .xlsx.sheetsource import SheetSource

if TYPE_CHECKING:
    from .engine import GridoraEngine

# Worksheet children that hold no cell coordinates (or, for <cols>, are rewritten on export).
_PLAIN_CHILDREN = frozenset({
    "sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData", "pageMargins",
    "pageSetup", "printOptions", "headerFooter", "phoneticPr", "sheetCalcPr",
})
_PART_PREFIXES = ("xl/charts/", "xl/pivotcache/", "xl/pivottables/", "xl/externallinks/")
_OPPOSITE = {"insert": "delete", "delete": "insert"}


def _refuse(reason: str, message: str) -> GridoraEngineError:
    return GridoraEngineError("operation_conflict", reason, message)


# -- checks --------------------------------------------------------------------------------------
def _check_request(eng: GridoraEngine, axis: str, op: str, at: int, count: int) -> None:
    if axis not in ("row", "col") or op not in _OPPOSITE or count < 1 or at < 0:
        raise bad_request("structure.bad_request", "The row or column change is not valid.")
    top = eng.limits.max_rows if axis == "row" else eng.limits.max_cols
    if at + count > top:
        raise validation_failed("structure.out_of_range", "The rows or columns lie outside the sheet limits.")


def _check_package(state: WorkbookState, sheet: SheetState) -> None:
    model = state.package
    if model is None:  # CSV workbook: nothing but cells
        return
    from .xlsx.exporter import _source_of

    src = _source_of(sheet)  # raises when the sheet XML cannot be rewritten safely
    assert isinstance(src, SheetSource)
    odd = sorted(set(src.features.children) - _PLAIN_CHILDREN)
    if odd:
        raise _refuse(
            "structure.unsupported_feature",
            "This sheet has features (merged cells, filters, validation, tables, comments, ...) that rows "
            "and columns cannot be inserted or deleted around yet.",
        )
    if any(n.lower().startswith(_PART_PREFIXES) for n in model.by_name):
        raise _refuse("structure.unsupported_feature", "The workbook has charts, pivot tables or external links.")
    name = sheet.name.casefold()
    for d in state.defined_names:
        if d.scope == sheet.id or name in d.ref.casefold():
            raise _refuse("structure.unsupported_feature", "A defined name refers to this sheet.")


def _check_loaded(eng: GridoraEngine, state: WorkbookState, sheet: SheetState) -> None:
    if any(k >= 4 for k in sheet.fkind.values()) or sheet.array_ranges:
        raise _refuse("structure.array_formulas", "This sheet has array formulas or data tables.")
    calc = state.calc
    if calc is not None and calc.built and any(
        (fk >> 40) == sheet.index for fk in (*calc.candidates, *calc.spill_rects, *calc.blocked_rects)
    ):
        raise _refuse("structure.spill", "This sheet has dynamic-array formulas that spill.")


# -- store movement ------------------------------------------------------------------------------
def _zeros(n: int) -> tuple[bytes, array[float], array[int]]:
    return bytes(n), array("d", bytes(8 * n)), array("H", bytes(2 * n))


def _clear_col(store: Any, c: int, rows: int) -> None:
    if rows:
        t, v, s = _zeros(rows)
        store.write_column(c, 0, t, v, s)


def _shift_store(store: Any, axis: str, op: str, at: int, count: int, rows: int, cols: int) -> None:
    if axis == "row":
        if at >= rows:
            return
        for c in range(cols):
            if op == "insert":
                t, v, s = store.column_arrays(c, at, rows - 1)
                zt, zv, zs = _zeros(count)
                store.write_column(c, at, zt + bytes(t), zv + v, zs + s)
            else:
                end = min(at + count, rows)
                if end < rows:
                    t, v, s = store.column_arrays(c, end, rows - 1)
                else:
                    t, v, s = _zeros(0)
                zt, zv, zs = _zeros(rows - at - len(t))
                store.write_column(c, at, bytes(t) + zt, v + zv, s + zs)
        return
    if at >= cols:
        return
    if op == "insert":
        for c in range(cols - 1, at - 1, -1):
            t, v, s = store.column_arrays(c, 0, rows - 1)
            store.write_column(c + count, 0, bytes(t), v, s)
        for c in range(at, min(at + count, cols)):
            _clear_col(store, c, rows)
        return
    for c in range(at + count, cols):
        t, v, s = store.column_arrays(c, 0, rows - 1)
        store.write_column(c - count, 0, bytes(t), v, s)
    for c in range(max(cols - count, at), cols):
        _clear_col(store, c, rows)


def _removed_cells(
    state: WorkbookState, sheet: SheetState, axis: str, at: int, count: int, rows: int, cols: int
) -> list[Cell]:
    """Every cell (with a value, a formula or a format) inside the block about to be deleted."""
    r0, r1, c0, c1 = (at, min(at + count, rows) - 1, 0, cols - 1) if axis == "row" else (
        0, rows - 1, at, min(at + count, cols) - 1)
    out: list[Cell] = []
    for c in range(c0, c1 + 1):
        if r1 < r0:
            break
        tags, _v, styles = sheet.store.column_arrays(c, r0, r1)
        for i in range(len(tags)):
            if tags[i] or styles[i]:
                out.append(read_cell(state, sheet, r0 + i, c))
    return out


# -- the operation -------------------------------------------------------------------------------
def _run(
    eng: GridoraEngine, state: WorkbookState, sheet: SheetState, axis: str, op: str, at: int, count: int,
    undo_of: str | None = None,
) -> tuple[list[Cell], list[tuple[int, Cell]]]:
    """Apply one operation. Returns (cells removed, [(sheet index, formula cell as it was)] for formulas the
    rewrite could not make reversible). Does not recalculate."""
    _check_request(eng, axis, op, at, count)
    _check_package(state, sheet)
    if sheet.lazy is not None:
        sheet.lazy.materialize_all()
    if eng._has_formulas(state):
        eng._calc(state).ensure_built()  # loads every sheet that has formulas
    _check_loaded(eng, state, sheet)
    rows, cols = sheet.store.extent()
    limit = eng.limits.max_rows if axis == "row" else eng.limits.max_cols
    if op == "insert" and (rows if axis == "row" else cols) + count > limit:
        raise validation_failed("structure.content_overflow", "Content would be pushed past the end of the sheet.")
    b = state.budget  # moving cells can allocate chunks: make sure that cannot fail half-way
    grow = cols * ((count >> 8) + 2) if axis == "row" else min(count, cols) * (((rows + 255) >> 8) + 1)
    if b.bytes_used + grow * CHUNK_BYTES > b.max_bytes:
        raise validation_failed("limits.store_bytes_exceeded", "The sheet needs more memory than is allowed.")

    removed = _removed_cells(state, sheet, axis, at, count, rows, cols) if op == "delete" else []
    block_lo, block_hi = at, at + count  # deleted indices [lo, hi)

    def inside(r: int, c: int) -> bool:
        i = r if axis == "row" else c
        return op == "delete" and block_lo <= i < block_hi

    # un-share shared formulas that would no longer be derivable from their master
    if sheet.fkind or any(s.fkind for s in state.sheets):
        calc = eng._calc(state)
        for si, s in enumerate(state.sheets):
            groups = [k for k, kind in s.fkind.items() if kind in (2, 3)]
            if not groups:
                continue
            if s is not sheet:
                from .model.shared import child_text

                groups = [k for k in groups if refers_to(
                    (s.formulas.get(k) if s.fkind.get(k) == 2 else child_text(s, k)) or "", s.name, sheet.name)]
            if groups:
                calc.unshare(si, groups)

    # rewrite formulas (computed first, applied only after every capacity check has passed)
    lost: list[tuple[int, Cell]] = []
    new_target: dict[int, str] = {}
    pending: list[tuple[SheetState, list[tuple[int, int, tuple[int, float, int, str | None]]]]] = []
    for si, s in enumerate(state.sheets):
        changes: list[tuple[int, int, tuple[int, float, int, str | None]]] = []
        for key, text in list(s.formulas.items()):
            r, c = key >> 14, key & 0x3FFF
            if s is sheet and inside(r, c):
                continue
            new_text, lossy = shift_formula(text, s.name, sheet.name, axis, op, at, count)
            if lossy:
                lost.append((si, read_cell(state, s, r, c)))
            if s is sheet:
                nr, nc = (transform_index(r, op, at, count), c) if axis == "row" else (r, transform_index(c, op, at, count))
                if nr is not None and nc is not None:
                    new_target[(nr << 14) | nc] = new_text
            elif new_text != text:
                tag, val, style = s.store.get(r, c)
                changes.append((r, c, (tag, val, style, new_text)))
        if changes:
            pending.append((s, changes))
    if len(removed) + len(lost) > eng.limits.max_patch_cells:
        raise too_large_for_history()
    for s, changes in pending:
        apply_all(s, changes)

    _shift_store(sheet.store, axis, op, at, count, rows, cols)
    sheet.formulas.clear()
    sheet.formulas.update(new_target)
    sheet.fkind.clear()
    sheet.shared_si.clear()
    sheet._shared_cache = None  # type: ignore[attr-defined]
    sheet.dirty.clear()
    sheet.orig.clear()
    sheet.bulk_rects.clear()
    sheet.restructured = True
    _log(sheet, axis, op, at, count, undo_of)
    state.calc = None  # the dependency graph is rebuilt from the formula texts when next needed
    return removed, lost


def _log(sheet: SheetState, axis: str, op: str, at: int, count: int, undo_of: str | None) -> None:
    """Keep the replayable list of operations (row heights, hidden rows and column widths are replayed
    from the original file on export). Undoing the last operation removes it instead of adding another."""
    if undo_of is not None and sheet.layout_ops and sheet.layout_ops[-1] == (axis, undo_of, at, count):
        sheet.layout_ops.pop()
    else:
        sheet.layout_ops.append((axis, op, at, count))
    src = getattr(sheet.lazy, "source", None)
    if src is not None:
        if sheet.base_hidden is None:
            sheet.base_hidden = set(src.hidden_rows)
        rows: set[int] = set(sheet.base_hidden)
        for ax, o, a, n in sheet.layout_ops:
            if ax == "row":
                rows = {x for x in (transform_index(r, o, a, n) for r in rows) if x is not None}
        src.hidden_rows = rows


def _recalculate(eng: GridoraEngine, state: WorkbookState) -> None:
    if eng._has_formulas(state):
        eng._calc(state).recalc(full=True)


def _dump(cell: Cell) -> dict[str, Any]:
    return cell.model_dump(mode="json", exclude_none=True)


# -- public entry points -------------------------------------------------------------------------
def apply_change(eng: GridoraEngine, wb: WorkbookHandle, change: dict[str, Any]) -> SheetStructureDelta:
    if change.get("type") != "axis_shift":
        raise bad_request("structure.unknown_change", "This kind of structure change is not supported.")
    try:
        sheet_id, axis, op = str(change["sheet_id"]), str(change["axis"]), str(change["op"])
        at, count = int(change["at"]), int(change["count"])
    except (KeyError, TypeError, ValueError):
        raise bad_request("structure.bad_request", "The row or column change is not valid.") from None
    return shift_axis(eng, wb, sheet_id, axis, op, at, count)


def shift_axis(
    eng: GridoraEngine, wb: WorkbookHandle, sheet_id: str, axis: str, op: str, at: int, count: int
) -> SheetStructureDelta:
    state = eng._state(wb)
    sheet = state.sheet(sheet_id)
    if sheet is None:
        raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
    removed, lost = _run(eng, state, sheet, axis, op, at, count)
    _recalculate(eng, state)
    return SheetStructureDelta(sheet_id=sheet_id, change={
        "type": "axis_shift", "axis": axis, "op": op, "at": at, "count": count,
        "removed": [_dump(c) for c in removed],
        "lost": [{"sheet": si, "cell": _dump(c)} for si, c in lost],
    })


def apply_structure(eng: GridoraEngine, wb: WorkbookHandle, delta: SheetStructureDelta, inverse: bool) -> None:
    ch = delta.change
    if ch.get("type") != "axis_shift":
        raise validation_failed("delta.unsupported_kind", "This kind of change is not supported yet.")
    state = eng._state(wb)
    sheet = state.sheet(delta.sheet_id)
    if sheet is None:
        raise validation_failed("delta.out_of_range", "The change refers to a sheet that does not exist.")
    try:
        axis, op, at, count = str(ch["axis"]), str(ch["op"]), int(ch["at"]), int(ch["count"])
        removed = [Cell.model_validate(x) for x in ch.get("removed", [])]
        lost = [(int(x["sheet"]), Cell.model_validate(x["cell"])) for x in ch.get("lost", [])]
    except (KeyError, TypeError, ValueError):
        raise validation_failed("delta.out_of_range", "The change is not valid.") from None
    if not inverse:
        _run(eng, state, sheet, axis, op, at, count)
        _recalculate(eng, state)
        return
    _run(eng, state, sheet, axis, _OPPOSITE.get(op, op), at, count, undo_of=op)
    if op == "delete":  # the cells that the deletion removed, back at their old positions
        changes = []
        for cell in removed:
            tag, val, style, text = cell_to_internal(state, cell)
            changes.append((cell.r, cell.c, (tag, val, style, text)))
        apply_all(sheet, changes)
    for si, cell in lost:  # formulas whose references the deletion/clipping could not give back
        if not 0 <= si < len(state.sheets):
            continue
        other = state.sheets[si]
        tag, val, style = other.store.get(cell.r, cell.c)
        text = cell.f.removeprefix("=") if cell.f else None
        apply_all(other, [(cell.r, cell.c, (tag, val, style, text))])
    state.calc = None
    _recalculate(eng, state)
