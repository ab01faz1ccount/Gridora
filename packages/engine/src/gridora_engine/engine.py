"""WorkbookEngine implementation (contract v0.2.0). E0: skeleton only.

Handles are NOT thread-safe; apps/api serializes access per document.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from gridora_contracts.models import (
    Cell,
    CellEdit,
    CellPatchDelta,
    CellWindow,
    ColumnarRange,
    CompatibilityReport,
    Delta,
    Range,
    SheetPatch,
    Window,
    Workbook,
)
from gridora_contracts.protocols import BlobStore, CsvOptions, WorkbookHandle

from .calc import Calculator
from .calc.calculator import resync_rect, split_fk
from .compat.report import build_report
from .csvio.importer import import_csv_file
from .csvio.writer import write_csv
from .errors import (
    GridoraEngineError,
    bad_request,
    too_large_for_history,
    validation_failed,
)
from .formula.parser import FormulaSyntaxError
from .formula.parser import parse as parse_formula
from .limits import ResourceLimits
from .model.cellview import cell_to_internal, internal_value, make_cell, read_cell
from .model.columnar import apply_range_snapshot, read_columnar, write_columnar
from .model.edits import Snap, apply_all, key_of, set_cell
from .model.values import ERR
from .model.workbook import SheetState, WorkbookState
from .xlsx.exporter import export_xlsx_file
from .xlsx.importer import import_xlsx_file

_ERR_NAME = 2  # index of #NAME? in model.values.ERR_CODES
_KNOWN_CONFIG = {"limits", "csv_neutralize_formulas", "csv_export_encoding"}
_EXPORT_ENCODINGS = {"utf-8-sig", "utf-8", "windows-1256"}


@dataclass
class Handle:
    """Opaque working-copy handle (satisfies contracts WorkbookHandle)."""

    id: str


class GridoraEngine:
    def __init__(self, config: Mapping[str, Any], blobs: BlobStore | None = None) -> None:
        self.blobs = blobs
        unknown = set(config) - _KNOWN_CONFIG
        if unknown:
            raise bad_request("config.unknown_key", "Unknown engine configuration key.")
        self.limits = ResourceLimits.from_mapping(config.get("limits", {}))
        self.csv_neutralize_formulas: bool = bool(config.get("csv_neutralize_formulas", True))
        enc = str(config.get("csv_export_encoding", "utf-8-sig"))
        if enc not in _EXPORT_ENCODINGS:
            raise bad_request("config.bad_encoding", "Unsupported CSV export encoding.")
        self.csv_export_encoding = enc
        self._open: dict[str, WorkbookState] = {}
        self.now = None  # tests may set a callable returning a datetime for TODAY()/NOW()

    # -- registry ---------------------------------------------------------------------------
    def _new_handle(self, state: WorkbookState) -> Handle:
        h = Handle(id=state.id)
        self._open[h.id] = state
        return h

    def _state(self, wb: WorkbookHandle) -> WorkbookState:
        try:
            return self._open[wb.id]
        except KeyError:
            raise bad_request(
                "handle.unknown", "The workbook handle is unknown or already closed."
            ) from None

    def close(self, wb: WorkbookHandle) -> None:
        """Release the working copy. Closing an unknown or closed handle is a no-op."""
        state = self._open.pop(wb.id, None)
        if state is not None:
            state.close()

    # -- contract methods not implemented yet (PLAN.md §15) -----------------------------------
    def import_xlsx(
        self, path: Path, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]:
        state = import_xlsx_file(path, self.limits, file_id)
        assert state.compat is not None
        return self._new_handle(state), state.to_model(), state.compat

    def import_csv(
        self, path: Path, options: CsvOptions, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook]:
        state = import_csv_file(path, options, self.limits, file_id)
        return self._new_handle(state), state.to_model()

    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow:
        state = self._state(wb)
        sheet = state.sheet(sheet_id)
        if sheet is None:
            raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
        sheet.ensure(window.row0, window.row0 + window.rows)
        cells = [
            make_cell(state, sheet, r, c, tag, val, style)
            for r, c, tag, val, style in sheet.store.window(
                window.row0, window.col0, window.rows, window.cols
            )
        ]
        return CellWindow(
            sheet_id=sheet_id, row0=window.row0, col0=window.col0,
            rows=window.rows, cols=window.cols, cells=cells,
        )

    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta:
        state, sheet = self._sheet(wb, sheet_id)
        limits = self.limits
        if len(edits) > limits.max_patch_cells:
            raise too_large_for_history()
        final: dict[int, CellEdit] = {}
        ftext: dict[int, str] = {}
        for e in edits:  # validate everything first; the last edit of a cell wins
            if e.r >= limits.max_rows or e.c >= limits.max_cols:
                raise validation_failed("edit.out_of_range", "A cell lies outside the sheet limits.")
            if e.formula is not None and e.value is not None:
                raise validation_failed("edit.value_and_formula", "A cell edit has either a value or a formula, not both.")
            if e.formula is not None:
                text = e.formula.removeprefix("=")
                if not text.strip() or len(text) > limits.max_field_chars:
                    raise validation_failed("edit.formula_syntax", "The formula is empty or too long.")
                try:
                    parse_formula(text)
                except FormulaSyntaxError:
                    raise validation_failed("edit.formula_syntax", "The formula is not valid.") from None
                ftext[key_of(e.r, e.c)] = text
            v = e.value
            if v is not None and v.k == "num" and (v.n != v.n or v.n in (float("inf"), float("-inf"))):
                raise validation_failed("edit.invalid_number", "The number is not a finite value.")
            if v is not None and v.k == "str" and len(v.s) > limits.max_field_chars:
                raise validation_failed("edit.string_too_long", "The text is longer than 32,767 characters.")
            k = key_of(e.r, e.c)
            final[k] = e
            if e.formula is None:
                ftext.pop(k, None)
        self._load_for_edit(sheet, [(k >> 14) for k in final])
        for k in final:
            if self._protected(sheet, k >> 14, k & 0x3FFF):
                raise validation_failed(
                    "edit.protected_formula_cell",
                    "This cell belongs to an array formula or data table and cannot be edited yet.",
                )
        calc = self._calc(state) if (ftext or self._has_formulas(state)) else None
        if calc is not None:
            calc.ensure_built()
            calc.unshare(sheet.index, list(final))
        before: dict[tuple[int, int, int], Cell] = {}
        changes: list[tuple[int, int, Snap]] = []
        for k, e in final.items():
            r, c = k >> 14, k & 0x3FFF
            before[(sheet.index, r, c)] = read_cell(state, sheet, r, c)
            _tag, _val, style = sheet.store.get(r, c)
            tag, val, style = internal_value(state, e.value, style)
            changes.append((r, c, (tag, val, style, ftext.get(k))))
        apply_all(sheet, changes)
        extra: list[tuple[int, int, int, Snap]] = []
        if calc is not None:
            for k in final:
                calc.set_formula(sheet.index, k, ftext.get(k))
            seeds = [(sheet.index, k >> 14, k & 0x3FFF) for k in final]
            fks = [(sheet.index << 40) | k for k in ftext]
            for fk in fks:  # an unknown function evaluates to #NAME? like Excel (it stays frozen afterwards)
                if fk in calc.frozen:
                    _s, r_, c_ = split_fk(fk)
                    _t, _v, st = sheet.store.get(r_, c_)
                    set_cell(sheet, r_, c_, (ERR, float(_ERR_NAME), st, sheet.formulas.get(fk & ((1 << 40) - 1))))
            extra = calc.recalc(seeds, fks)
        return self._build_patch(state, sheet, before, extra)

    def _build_patch(
        self, state: WorkbookState, sheet: SheetState, before: dict[tuple[int, int, int], Cell],
        extra: list[tuple[int, int, int, Snap]],
    ) -> CellPatchDelta:
        for s_, r_, c_, snap in extra:
            if (s_, r_, c_) not in before:
                tag, val, style, _text = snap
                other = state.sheets[s_]
                before[(s_, r_, c_)] = make_cell(state, other, r_, c_, tag, val, style)
        per: dict[int, tuple[list[Cell], list[Cell]]] = {}
        for (s_, r_, c_), b in before.items():
            bl, al = per.setdefault(s_, ([], []))
            bl.append(b)
            al.append(read_cell(state, state.sheets[s_], r_, c_))
        own_b, own_a = per.pop(sheet.index, ([], []))
        others = [
            SheetPatch(sheet_id=state.sheets[s_].id, before=bl, after=al) for s_, (bl, al) in sorted(per.items())
        ]
        return CellPatchDelta(sheet_id=sheet.id, before=own_b, after=own_a, others=others)

    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None:
        if delta.kind == "range_snapshot":
            state, sheet = self._sheet(wb, delta.sheet_id)
            self._before_bulk(state)
            apply_range_snapshot(state, sheet, delta, inverse, self.limits, self.blobs)
            rg = delta.range
            self._after_bulk(state, sheet, rg.r0, rg.c0, rg.r1, rg.c1)
            return
        if delta.kind != "cell_patch":
            raise validation_failed("delta.unsupported_kind", "This kind of change is not supported yet.")
        state, sheet = self._sheet(wb, delta.sheet_id)
        cells = delta.before if inverse else delta.after
        if len(cells) > self.limits.max_patch_cells:
            raise too_large_for_history()
        for cell in cells:
            if cell.r >= self.limits.max_rows or cell.c >= self.limits.max_cols or (cell.s or 0) > 65535:
                raise validation_failed("delta.out_of_range", "The change refers to a cell outside the sheet.")
        self._load_for_edit(sheet, [cell.r for cell in cells])
        changes: list[tuple[int, int, Snap]] = []
        for cell in cells:
            tag, val, style, text = cell_to_internal(state, cell)
            changes.append((cell.r, cell.c, (tag, val, style, text)))
        apply_all(sheet, changes)
        self._sync_calc(state, sheet, [(c.r, c.c) for c in cells])
        for other in delta.others:
            osheet = state.sheet(other.sheet_id)
            if osheet is None:
                raise validation_failed("delta.out_of_range", "The change refers to a sheet that does not exist.")
            ocells = other.before if inverse else other.after
            self._load_for_edit(osheet, [c.r for c in ocells])
            ochanges = []
            for cell in ocells:
                tag, val, style, text = cell_to_internal(state, cell)
                ochanges.append((cell.r, cell.c, (tag, val, style, text)))
            apply_all(osheet, ochanges)
            self._sync_calc(state, osheet, [(c.r, c.c) for c in ocells])

    # -- ColumnarEngine (contract 0.4.1) ------------------------------------------------------
    def read_range_columnar(self, wb: WorkbookHandle, rng: Range) -> ColumnarRange:
        state, sheet = self._sheet(wb, rng.sheet_id)
        return read_columnar(state, sheet, rng, self.limits)

    def write_range_columnar(self, wb: WorkbookHandle, rng: Range, data: ColumnarRange) -> Delta:
        state, sheet = self._sheet(wb, rng.sheet_id)
        self._before_bulk(state)
        if state.calc is not None and state.calc.built:
            shared = [k for k, kind in sheet.fkind.items()
                      if kind in (2, 3) and rng.r0 <= (k >> 14) <= rng.r1 and rng.c0 <= (k & 0x3FFF) <= rng.c1]
            if shared:
                state.calc.unshare(sheet.index, shared)
        delta = write_columnar(state, sheet, rng, data, self.limits, self.blobs)
        self._after_bulk(state, sheet, rng.r0, rng.c0, rng.r1, rng.c1)
        return delta

    # -- helpers ----------------------------------------------------------------------------
    def _sheet(self, wb: WorkbookHandle, sheet_id: str) -> tuple[WorkbookState, SheetState]:
        state = self._state(wb)
        sheet = state.sheet(sheet_id)
        if sheet is None:
            raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
        return state, sheet

    @staticmethod
    def _load_for_edit(sheet: SheetState, rows: list[int]) -> None:
        """Make sure every row about to change is materialized BEFORE it changes (a later lazy
        parse would overwrite edits). Sheets with shared/array formulas are loaded completely so
        the protection check sees every formula group."""
        lazy = sheet.lazy
        if lazy is None:
            return
        src = getattr(lazy, "source", None)
        if src is not None and (src.array_count or src.shared_count):
            lazy.materialize_all()
            return
        for block in sorted({r >> 8 for r in rows}):
            lazy.ensure(block << 8, (block << 8) + 1)

    @staticmethod
    def _protected(sheet: SheetState, r: int, c: int) -> bool:
        if sheet.fkind.get((r << 14) | c, 0) >= 4:  # array formula / data table (shared groups are un-shared)
            return True
        return any(r0 <= r <= r1 and c0 <= c <= c1 for r0, c0, r1, c1 in sheet.array_ranges)

    def recalculate(self, wb: WorkbookHandle) -> None:
        state = self._state(wb)
        if not self._has_formulas(state):
            return
        self._calc(state).recalc(full=True)

    # -- calculation helpers (E7) -------------------------------------------------------------
    def _calc(self, state: WorkbookState) -> Calculator:
        if state.calc is None:
            state.calc = Calculator(state, self.now)
        return cast(Calculator, state.calc)

    @staticmethod
    def _has_formulas(state: WorkbookState) -> bool:
        if state.calc is not None and state.calc.built:
            return bool(state.calc.has_formulas())
        for s in state.sheets:
            if s.formulas or any(k >= 2 for k in s.fkind.values()):
                return True
            src = getattr(s.lazy, "source", None)
            if src is not None and src.formula_count:
                return True
        return False

    def _sync_calc(self, state: WorkbookState, sheet: SheetState, cells: list[tuple[int, int]]) -> None:
        """Keep the dependency graph in step with formula texts that a delta restored (no recalculation)."""
        calc = state.calc
        if calc is None or not calc.built:
            if not any(sheet.formulas.get((r << 14) | c) for r, c in cells):
                return
            calc = self._calc(state)
            calc.ensure_built()  # reads the current formula texts, including the restored ones
            return
        for r, c in cells:
            key = (r << 14) | c
            calc.set_formula(sheet.index, key, sheet.formulas.get(key))

    def _before_bulk(self, state: WorkbookState) -> None:
        """Load every formula sheet completely BEFORE a bulk write: a later full parse of a lazy sheet
        would overwrite the bulk-written rectangle (only per-cell edits survive a re-parse)."""
        if self._has_formulas(state):
            self._calc(state).ensure_built()

    def _after_bulk(self, state: WorkbookState, sheet: SheetState, r0: int, c0: int, r1: int, c1: int) -> None:
        """A bulk write (range snapshot / columnar) replaced values and formulas in a rectangle:
        re-register its formulas and recompute everything that depends on it. The recomputed
        dependents are derived data: they are not part of the range delta, and undo recomputes them again."""
        if not self._has_formulas(state):
            return
        calc = self._calc(state)
        calc.ensure_built()
        resync_rect(calc, sheet.index, r0, c0, r1, c1)
        calc.recalc(seed_rects=[(sheet.index, r0, c0, r1, c1)])

    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport:
        return export_xlsx_file(self._state(wb), path, self.limits)

    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> CompatibilityReport:
        state = self._state(wb)
        sheet = state.sheet(sheet_id)
        if sheet is None:
            raise GridoraEngineError("not_found", "sheet.unknown", "The sheet does not exist.")
        n = write_csv(
            path, sheet.store, state.strings, self.csv_export_encoding,
            self.csv_neutralize_formulas,
        )
        return build_report("export", {"csv.formula_text_neutralized": n})
