"""Contract <-> internal conversion for single cells (shared by get_cells, edits and deltas)."""
from __future__ import annotations

from gridora_contracts.models import Cell, CellValue, DateValue

from ..errors import validation_failed
from .dates import iso_to_serial, serial_to_iso
from .values import BOOL, ERR, ERR_CODES, NOVAL, NUM, STR, to_contract_value
from .workbook import SheetState, WorkbookState

_ERR_INDEX = {c: i for i, c in enumerate(ERR_CODES)}


def make_cell(
    state: WorkbookState, sheet: SheetState, r: int, c: int, tag: int, val: float, style: int
) -> Cell:
    """Contract Cell for one stored slot (tag 0 = empty cell)."""
    styles = state.styles
    v = to_contract_value(tag, val, state.strings)
    fmt = None
    if style and styles is not None:
        if tag == NUM and style < len(styles.xf_is_date) and styles.xf_is_date[style]:
            iso = serial_to_iso(val, state.date_system)
            if iso is not None:
                v = DateValue.model_construct(k="date", iso=iso)
        if style < len(styles.xf_numfmt) and styles.xf_numfmt[style]:
            fmt = str(styles.xf_numfmt[style])
    text = sheet.formulas.get((r << 14) | c) if sheet.formulas else None
    return Cell.model_construct(
        r=r, c=c, v=v, f=None if text is None else "=" + text, s=style or None, t=fmt
    )


def read_cell(state: WorkbookState, sheet: SheetState, r: int, c: int) -> Cell:
    tag, val, style = sheet.store.get(r, c)
    return make_cell(state, sheet, r, c, tag, val, style)


def internal_value(
    state: WorkbookState, v: CellValue | None, style: int
) -> tuple[int, float, int]:
    """(tag, val, style) for a contract value. DateValue needs a date format (see errors)."""
    if v is None:
        return 0, 0.0, style
    if v.k == "num":
        return NUM, v.n, style
    if v.k == "str":
        return STR, float(state.strings.intern(v.s)), style
    if v.k == "bool":
        return BOOL, 1.0 if v.b else 0.0, style
    if v.k == "err":
        return ERR, float(_ERR_INDEX[v.e]), style
    # date
    styles = state.styles
    if styles is None or not any(styles.xf_is_date):
        raise validation_failed(
            "edit.date_needs_format", "This workbook has no date format to display a date with."
        )
    if not (0 < style < len(styles.xf_is_date) and styles.xf_is_date[style]):
        style = styles.xf_is_date.index(True)
    try:
        return NUM, iso_to_serial(v.iso, state.date_system), style
    except ValueError:
        raise validation_failed("edit.invalid_date", "The date value is not valid.") from None


def cell_to_internal(
    state: WorkbookState, cell: Cell
) -> tuple[int, float, int, str | None]:
    """(tag, val, style, formula text without '=') from a Cell of a delta (trusted shape)."""
    tag, val, style = internal_value(state, cell.v, cell.s or 0)
    text = None
    if cell.f:
        text = cell.f.removeprefix("=")
        if tag == 0:
            tag = NOVAL
    return tag, val, style, text
