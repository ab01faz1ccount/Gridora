from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from gridora_contracts.models import CompatibilityReport, DefinedName, Frozen, SheetMeta, Workbook

from .dates import DateSystem
from .sheet import SheetStore, StoreBudget
from .values import StringTable

# Fixed namespace: sheet ids are derived (uuid5) so importing the same file gives the same ids.
SHEET_ID_NAMESPACE = uuid.UUID("6f1d3a52-9c4e-4b1a-8f27-2a5d7c9e0b41")


def stable_sheet_id(file_id: str, index: int, name: str) -> str:
    """Deterministic sheet id: same file id + position + name -> same id (history, URLs and
    replays survive re-imports). Unique within a workbook because the position is included."""
    return str(uuid.uuid5(SHEET_ID_NAMESPACE, f"{file_id}\x00{index}\x00{name}"))


class Materializer(Protocol):
    """Lazy backing of a sheet (XLSX): makes rows available in the SheetStore on demand."""

    def ensure(self, row_lo: int, row_hi: int) -> None: ...
    def materialize_all(self) -> None: ...
    def used_hint(self) -> tuple[int, int]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Props:
    """Resolved look of one cell format (xf): what the grid shows and the format toolbar changes."""

    number_format: str | None = None  # code; None = General
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    font_name: str | None = None
    font_size: float | None = None
    font_color: str | None = None  # "#RRGGBB"
    fill_color: str | None = None
    halign: str | None = None  # left | center | right | justify
    wrap: bool = False


@dataclass
class Derived:
    """A format made at run time from an imported one (`root`) by changing `props`."""

    root: int
    props: Props
    placeholder: bool = False  # filled in only to keep ids aligned after a replay


@dataclass
class StyleInfo:
    """Per cell-format (xf) index: number format id and whether it shows a date/time, plus the
    resolved look (`props`, imported xfs) and the formats made since import (`derived`, ids from
    `n_imported` on). Derived formats are written into styles.xml by the exporter."""

    xf_numfmt: list[int] = field(default_factory=list)
    xf_is_date: list[bool] = field(default_factory=list)
    xf_code: list[str | None] = field(default_factory=list)  # number format code, None = General
    props: list[Props] | None = None  # imported xfs; None when styles.xml could not be read
    n_imported: int = 0
    derived: list[Derived] = field(default_factory=list)
    codes: dict[int, str] = field(default_factory=dict)  # custom number formats by id
    new_codes: dict[int, str] = field(default_factory=dict)  # those added since import


@dataclass
class SheetState:
    id: str
    name: str
    index: int
    store: SheetStore
    rtl: bool = False
    visible: Literal["visible", "hidden", "very_hidden"] = "visible"
    frozen: Frozen | None = None
    lazy: Materializer | None = None
    part_name: str = ""
    formulas: dict[int, str] = field(default_factory=dict)  # (r << 14) | c -> text without '='
    fkind: dict[int, int] = field(default_factory=dict)  # see xlsx.cellparse (2..5)
    array_ranges: list[tuple[int, int, int, int]] = field(default_factory=list)  # r0, c0, r1, c1
    shared_si: dict[int, int] = field(default_factory=dict)  # cell key -> shared formula index (E7)
    # Cells whose content differs from the file as imported (used by export, E6), and the
    # imported content of each: key -> (tag, val, style, formula text or None).
    dirty: set[int] = field(default_factory=set)
    orig: dict[int, tuple[int, float, int, str | None]] = field(default_factory=dict)
    # Rectangles written in bulk (range snapshots): the exporter regenerates every cell inside them.
    bulk_rects: list[tuple[int, int, int, int]] = field(default_factory=list)  # r0, c0, r1, c1
    bulk_formulas_changed: bool = False
    # Rows/columns inserted or deleted since import (axis, op, at, count), oldest first. A sheet with
    # `restructured` set is exported by regenerating its whole sheetData (xlsx.relayout).
    restructured: bool = False
    layout_ops: list[tuple[str, str, int, int]] = field(default_factory=list)
    base_hidden: set[int] | None = None  # hidden rows as imported (the live set is replayed from it)

    def ensure(self, row_lo: int, row_hi: int) -> None:
        if self.lazy is not None:
            self.lazy.ensure(row_lo, row_hi)

    def meta(self) -> SheetMeta:
        rows, cols = self.store.used_size()
        if self.lazy is not None:
            hr, hc = self.lazy.used_hint()
            rows, cols = max(rows, hr), max(cols, hc)
        return SheetMeta(
            id=self.id, name=self.name, index=self.index, visible=self.visible,
            row_count=rows, col_count=cols, frozen=self.frozen, rtl=self.rtl,
        )


@dataclass
class WorkbookState:
    id: str
    file_id: str
    name: str
    budget: StoreBudget
    strings: StringTable = field(default_factory=StringTable)
    sheets: list[SheetState] = field(default_factory=list)
    date_system: DateSystem = "1900"
    compat: CompatibilityReport | None = None
    defined_names: list[DefinedName] = field(default_factory=list)
    styles: StyleInfo | None = None
    package: Any = None  # PackageModel for XLSX workbooks (kept open: parts stream from it)
    findings: list[Any] = field(default_factory=list)  # lazily discovered anomalies (E6 report)
    calc: Any = None  # gridora_engine.calc.Calculator, created on first need (E7)

    def sheet(self, sheet_id: str) -> SheetState | None:
        for s in self.sheets:
            if s.id == sheet_id:
                return s
        return None

    def to_model(self) -> Workbook:
        return Workbook(
            id=self.id, file_id=self.file_id, name=self.name,
            sheets=[s.meta() for s in self.sheets], defined_names=self.defined_names,
            date_system=self.date_system, compat=self.compat,
        )

    def close(self) -> None:
        for s in self.sheets:
            if s.lazy is not None:
                s.lazy.close()
        if self.package is not None:
            self.package.close()
            self.package = None
