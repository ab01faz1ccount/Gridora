"""Env implementation over a WorkbookState (what the formula evaluator reads through)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..formula import xlerrors as E
from ..formula.dates import ymd_to_serial
from ..model.values import BOOL, ERR, ERR_CODES, NUM, STR
from ..model.workbook import WorkbookState

if TYPE_CHECKING:  # pragma: no cover
    from .calculator import Calculator


class WorkbookEnv:
    def __init__(self, state: WorkbookState, calc: Calculator) -> None:
        self.state = state
        self.calc = calc
        self.date1904 = state.date_system == "1904"
        self._names: dict[str, str] = {}
        self._now: float | None = None

    # -- Env protocol -------------------------------------------------------------------------
    def sheet_index(self, name: str) -> int | None:
        low = name.lower()
        for i, s in enumerate(self.state.sheets):
            if s.name.lower() == low:
                return i
        return None

    def cell(self, s: int, r: int, c: int) -> Any:
        sheet = self.state.sheets[s]
        lazy = sheet.lazy
        if lazy is not None and not _loaded(lazy, r):
            lazy.ensure(r, r + 1)
        tag, val, _style = sheet.store.get(r, c)
        if tag == NUM:
            return val
        if tag == STR:
            return self.state.strings.get(int(val))
        if tag == BOOL:
            return val != 0
        if tag == ERR:
            code = ERR_CODES[int(val)]
            return E.BY_CODE.get(code) or E.XlError(code)
        return None

    def used_size(self, s: int) -> tuple[int, int]:
        sheet = self.state.sheets[s]
        rows, cols = sheet.store.used_size()
        if sheet.lazy is not None:
            hr, hc = sheet.lazy.used_hint()
            rows, cols = max(rows, hr), max(cols, hc)
        return rows, cols

    def defined_name(self, name: str, s: int) -> str | None:
        low = name.lower()
        sheet_id = self.state.sheets[s].id
        found: str | None = None
        for dn in self.state.defined_names:
            if dn.name.lower() != low:
                continue
            if dn.scope == sheet_id:
                return dn.ref.removeprefix("=")
            if dn.scope == "workbook":
                found = dn.ref.removeprefix("=")
        return found

    def now_serial(self) -> float:
        if self._now is None:
            fixed = self.calc.now
            n = fixed() if fixed is not None else datetime.now()
            base = ymd_to_serial(n.year, n.month, n.day, self.date1904) or 0.0
            self._now = base + (n.hour * 3600 + n.minute * 60 + n.second) / 86400
        return self._now

    def reset_clock(self) -> None:
        self._now = None

    def is_subtotal_cell(self, s: int, r: int, c: int) -> bool:
        return self.calc.is_subtotal((s << 40) | (r << 14) | c)


def _loaded(lazy: Any, r: int) -> bool:
    return getattr(lazy, "_all", False) or (r >> 8) in lazy.parsed_blocks
