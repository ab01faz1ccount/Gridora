from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from gridora_contracts.models import CompatibilityReport, Frozen, SheetMeta, Workbook

from .dates import DateSystem
from .sheet import SheetStore, StoreBudget
from .values import StringTable


@dataclass
class SheetState:
    id: str
    name: str
    index: int
    store: SheetStore
    rtl: bool = False
    visible: Literal["visible", "hidden", "very_hidden"] = "visible"
    frozen: Frozen | None = None

    def meta(self) -> SheetMeta:
        rows, cols = self.store.used_size()
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

    def sheet(self, sheet_id: str) -> SheetState | None:
        for s in self.sheets:
            if s.id == sheet_id:
                return s
        return None

    def to_model(self) -> Workbook:
        return Workbook(
            id=self.id, file_id=self.file_id, name=self.name,
            sheets=[s.meta() for s in self.sheets],
            date_system=self.date_system, compat=self.compat,
        )
