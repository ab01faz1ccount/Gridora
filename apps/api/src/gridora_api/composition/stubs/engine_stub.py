"""STUB WorkbookEngine. NOT a spreadsheet engine.

What it is: an in-memory, single-sheet, CSV-only stand-in so apps/api and apps/web can be built
and tested before packages/engine exists. What it is not: it reads no XLSX, evaluates no formula,
keeps no styles, preserves nothing. Every import carries a compatibility item saying so.

Replaced by gridora_engine via GRIDORA_ENGINE=real (composition/wiring.py).
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gridora_contracts.models import (
    Cell,
    CellEdit,
    CellPatchDelta,
    CellValue,
    CellWindow,
    CompatibilityReport,
    CompatItem,
    CompatSummary,
    Delta,
    ErrorDetail,
    NumValue,
    SheetMeta,
    StrValue,
    Window,
    Workbook,
)
from gridora_contracts.protocols import CsvOptions, WorkbookHandle

from ...core.errors import DomainError

SHEET_ID_NS = uuid.UUID("6f1d3a52-0000-4000-8000-000000000001")


@dataclass
class StubHandle:
    id: str
    sheet_id: str
    cells: dict[tuple[int, int], Cell] = field(default_factory=dict)
    closed: bool = False

    def extent(self) -> tuple[int, int]:
        if not self.cells:
            return 0, 0
        return max(r for r, _ in self.cells) + 1, max(c for _, c in self.cells) + 1


def _decode(raw: bytes, encoding: str | None) -> str:
    if encoding:
        return raw.decode(encoding)
    for enc in ("utf-8-sig", "cp1256"):  # UTF-8 (with/without BOM), then Windows-1256
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DomainError("import_failed", "The text encoding of this file is not supported.")


def _value(text: str, infer: bool) -> CellValue | None:
    if text == "":
        return None
    if infer:
        try:
            return NumValue(n=float(text))
        except ValueError:
            pass
    return StrValue(s=text)  # note: "=..." stays TEXT here; the stub never evaluates formulas


class StubEngine:
    def __init__(self, max_cells: int = 5_000_000) -> None:
        self.max_cells = max_cells

    # ------------------------------------------------------------- import ----
    def import_xlsx(
        self, path: Path, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook, CompatibilityReport]:
        raise DomainError(
            "unsupported_workbook",
            "The stub engine cannot read XLSX files; only CSV is supported until the real "
            "engine is installed.",
            details=[ErrorDetail(code="stub.xlsx_unsupported", message="stub engine: CSV only")],
        )

    def import_csv(
        self, path: Path, options: CsvOptions, *, file_id: str | None = None
    ) -> tuple[WorkbookHandle, Workbook]:
        text = _decode(path.read_bytes(), getattr(options, "encoding", None))
        delim = getattr(options, "delimiter", None)
        if not delim:
            try:
                delim = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
            except csv.Error:
                delim = ","
        infer = bool(getattr(options, "infer_types", True))
        wid = str(uuid.uuid4())
        # Sheet ids must be STABLE across re-imports of the same file: history deltas refer to
        # them and are replayed onto a fresh import after a restart or cache eviction.
        sheet_id = str(uuid.uuid5(SHEET_ID_NS, f"{file_id or wid}:0"))
        h = StubHandle(id=wid, sheet_id=sheet_id)
        for r, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
            for c, raw in enumerate(row):
                v = _value(raw, infer)
                if v is not None:
                    h.cells[(r, c)] = Cell(r=r, c=c, v=v)
            if len(h.cells) > self.max_cells:
                raise DomainError("import_failed", "The sheet is too large for the stub engine.")
        rows, cols = h.extent()
        item = CompatItem(
            code="stub.engine",
            status="partial",
            preserved=False,
            editable=True,
            message="Stub engine: CSV only. Formulas are not evaluated; no styles are kept.",
        )
        report = CompatibilityReport(
            source="import",
            generated_at=datetime.now(UTC),
            items=[item],
            summary=CompatSummary(partial=1),
        )
        wb = Workbook(
            id=wid,
            file_id=file_id or "",
            name=path.stem,
            sheets=[SheetMeta(id=sheet_id, name="Sheet1", index=0, row_count=rows, col_count=cols)],
            compat=report,
        )
        return h, wb

    def close(self, wb: WorkbookHandle) -> None:
        h = self._h(wb)
        h.cells.clear()
        h.closed = True

    # ------------------------------------------------------------- reading ----
    def _h(self, wb: Any) -> StubHandle:
        if not isinstance(wb, StubHandle) or wb.closed:
            raise DomainError("not_found", "The workbook is not open.")
        return wb

    def _sheet(self, h: StubHandle, sheet_id: str) -> None:
        if sheet_id != h.sheet_id:
            raise DomainError("not_found", "Unknown sheet.")

    def get_cells(self, wb: WorkbookHandle, sheet_id: str, window: Window) -> CellWindow:
        h = self._h(wb)
        self._sheet(h, sheet_id)
        r1, c1 = window.row0 + window.rows, window.col0 + window.cols
        cells = [
            cell
            for (r, c), cell in sorted(h.cells.items())
            if window.row0 <= r < r1 and window.col0 <= c < c1
        ]
        return CellWindow(
            sheet_id=sheet_id,
            row0=window.row0,
            col0=window.col0,
            rows=window.rows,
            cols=window.cols,
            cells=cells,
        )

    # ------------------------------------------------------------- editing ----
    def apply_cell_edits(self, wb: WorkbookHandle, sheet_id: str, edits: list[CellEdit]) -> Delta:
        h = self._h(wb)
        self._sheet(h, sheet_id)
        for i, e in enumerate(edits):
            if e.formula is not None:
                raise DomainError(
                    "validation_failed",
                    "The stub engine cannot store formulas.",
                    details=[
                        ErrorDetail(
                            code="stub.formulas_unsupported",
                            path=f"/edits/{i}/formula",
                            message="formulas need the real engine",
                        )
                    ],
                )
        before: list[Cell] = []
        after: list[Cell] = []
        for e in edits:
            old = h.cells.get((e.r, e.c))
            before.append(old or Cell(r=e.r, c=e.c))
            new = Cell(r=e.r, c=e.c, v=e.value)
            after.append(new)
            if e.value is None:
                h.cells.pop((e.r, e.c), None)
            else:
                h.cells[(e.r, e.c)] = new
        return CellPatchDelta(sheet_id=sheet_id, before=before, after=after)

    def apply_delta(self, wb: WorkbookHandle, delta: Delta, *, inverse: bool) -> None:
        h = self._h(wb)
        if not isinstance(delta, CellPatchDelta):
            raise DomainError("operation_conflict", "The stub engine only replays cell patches.")
        self._sheet(h, delta.sheet_id)
        for cell in delta.before if inverse else delta.after:
            if cell.v is None and cell.f is None:
                h.cells.pop((cell.r, cell.c), None)
            else:
                h.cells[(cell.r, cell.c)] = cell  # exactly as recorded; no recalculation

    def recalculate(self, wb: WorkbookHandle) -> None:
        self._h(wb)  # nothing to do: formulas are not supported

    # -------------------------------------------------------------- export ----
    def export_xlsx(self, wb: WorkbookHandle, path: Path) -> CompatibilityReport:
        raise DomainError(
            "unsupported_workbook", "The stub engine cannot write XLSX; only CSV export exists."
        )

    def export_csv(self, wb: WorkbookHandle, sheet_id: str, path: Path) -> CompatibilityReport:
        """Contract v0.3.0 (CC-9): returns a report, so nothing is changed silently.

        Text cells that a spreadsheet would run as a formula (leading = + - @, tab or CR) are
        prefixed with an apostrophe (OWASP CSV-injection guidance); each one is reported with
        its location. Numbers are never touched, so "-5" stays -5."""
        h = self._h(wb)
        self._sheet(h, sheet_id)
        rows, cols = h.extent()
        neutralized: list[str] = []
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            for r in range(rows):
                out: list[str] = []
                for c in range(cols):
                    cell = h.cells.get((r, c))
                    v = cell.v if cell else None
                    text = "" if v is None else _text(v)
                    if isinstance(v, StrValue) and text[:1] in _FORMULA_LEADERS:
                        text = "'" + text
                        neutralized.append(f"{_col_letters(c)}{r + 1}")
                    out.append(text)
                w.writerow(out)
        items = [
            CompatItem(
                code="export.csv.formula_neutralized",
                status="partial",
                preserved=False,
                editable=True,
                message="Text that looks like a formula was prefixed with an apostrophe.",
                location=loc,
            )
            for loc in neutralized
        ]
        return CompatibilityReport(
            source="export",
            generated_at=datetime.now(UTC),
            items=items,
            summary=CompatSummary(partial=len(items)),
        )


_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _col_letters(c: int) -> str:
    out = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        out = chr(65 + rem) + out
    return out


def _text(v: CellValue) -> str:
    if isinstance(v, NumValue):
        return repr(int(v.n)) if v.n == int(v.n) else repr(v.n)
    if isinstance(v, StrValue):
        return v.s
    d = v.model_dump()
    return str(d.get("b", d.get("e", d.get("iso", ""))))


def create_engine(config: dict[str, Any] | None = None) -> StubEngine:
    """Same factory name/signature as gridora_engine.create_engine (contracts protocols.py)."""
    return StubEngine(max_cells=int((config or {}).get("max_cells", 5_000_000)))
