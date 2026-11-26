"""Cell formatting: change the look of a range (bold, fonts, colours, number formats ...).

A format is an index (`Cell.s`) into the workbook's cell formats. Changing a cell's look finds or makes
the format that has the wanted properties and stores its index in the cell; values and formulas stay.
"""
from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any

from gridora_contracts.models import CellPatchDelta, Range
from gridora_contracts.models import StyleInfo as StyleOut

from .errors import validation_failed
from .model.cellview import read_cell
from .model.edits import set_cell, snapshot
from .model.workbook import Props, StyleInfo
from .xlsx import styles as xs

if TYPE_CHECKING:
    from gridora_contracts.protocols import WorkbookHandle

    from .engine import GridoraEngine

MAX_FORMAT_CELLS = 50_000
_KEYS = {f.name for f in fields(Props)}


def table_of(state: Any) -> StyleInfo:
    """The workbook's cell formats; a workbook with none of its own (CSV) gets the default one."""
    if state.styles is None or not state.styles.xf_numfmt:
        state.styles = xs.default_table()
    return state.styles  # type: ignore[no-any-return]


def to_out(table: StyleInfo, xf: int) -> StyleOut:
    p = xs.props_of(table, xf)
    base = None if xf < table.n_imported else table.derived[xf - table.n_imported].root
    return StyleOut(
        id=xf, number_format=p.number_format, bold=p.bold, italic=p.italic, underline=p.underline, strike=p.strike,
        font_name=p.font_name, font_size=p.font_size, font_color=p.font_color, fill_color=p.fill_color,
        halign=p.halign, wrap=p.wrap, base_id=base,
    )


def ensure_from_delta(state: Any, specs: list[StyleOut]) -> None:
    table = table_of(state)
    xs.ensure_derived(table, [
        (s.id, s.base_id or 0, Props(
            number_format=s.number_format, bold=s.bold, italic=s.italic, underline=s.underline,
            font_name=s.font_name, font_size=s.font_size, font_color=s.font_color, fill_color=s.fill_color,
            halign=s.halign, wrap=s.wrap,
        )) for s in specs
    ])


def _clean(change: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in change.items():
        if k not in _KEYS:
            raise validation_failed("format.unknown_property", "This formatting property does not exist.")
        if k in ("bold", "italic", "underline", "strike", "wrap"):
            v = bool(v)  # None puts the default (off) back
        elif k == "number_format" and v in ("", "General"):
            v = None
        elif k in ("font_color", "fill_color") and v is not None:
            v = str(v).upper()
        out[k] = v
    return out


def format_cells(engine: GridoraEngine, wb: WorkbookHandle, rng: Range, change: dict[str, Any]) -> CellPatchDelta:
    state, sheet = engine._sheet(wb, rng.sheet_id)
    limits = engine.limits
    if not (0 <= rng.r0 <= rng.r1 < limits.max_rows and 0 <= rng.c0 <= rng.c1 < limits.max_cols):
        raise validation_failed("format.out_of_range", "The range lies outside the sheet.")
    if (rng.r1 - rng.r0 + 1) * (rng.c1 - rng.c0 + 1) > MAX_FORMAT_CELLS:
        raise validation_failed("format.too_large", "Format at most 50,000 cells at a time.")
    change = _clean(change)
    if not change:
        raise validation_failed("format.empty", "There is nothing to change.")
    table = table_of(state)
    engine._load_for_edit(sheet, list(range(rng.r0, rng.r1 + 1)))
    before = []
    plan: dict[int, int] = {}
    cells = [(r, c) for r in range(rng.r0, rng.r1 + 1) for c in range(rng.c0, rng.c1 + 1)]
    for r, c in cells:
        before.append(read_cell(state, sheet, r, c))
        tag, val, style, text = snapshot(sheet, r, c)
        if style not in plan:
            plan[style] = xs.derive(table, style, change)
        if plan[style] != style:
            set_cell(sheet, r, c, (tag, val, plan[style], text))
    after = [read_cell(state, sheet, r, c) for r, c in cells]
    used = {c.s for c in after if c.s} | {c.s for c in before if c.s}
    made = [to_out(table, i) for i in sorted(used) if i >= table.n_imported]
    return CellPatchDelta(sheet_id=sheet.id, before=before, after=after, styles=made)
