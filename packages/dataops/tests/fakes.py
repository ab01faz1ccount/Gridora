"""In-memory ExecContext used by tests (dataops never imports the real engine)."""
from __future__ import annotations

from typing import Any

from gridora_contracts.models import Cell, CellPatchDelta, CellValue, Delta, NumValue, Range, StrValue


def num(n: float) -> CellValue:
    return NumValue(n=n)


def txt(s: str) -> CellValue:
    return StrValue(s=s)


class FakeExecContext:
    user_id = "u1"
    workspace_id = "w1"

    def __init__(self, sheet_id: str = "s1", store: Any = None) -> None:
        self.sheet_id = sheet_id
        self.store = store
        self.grid: dict[tuple[int, int], Cell] = {}
        self.reads = 0
        self.writes = 0

    # -- test helpers
    def put(self, r: int, c: int, v: CellValue | None = None, f: str | None = None) -> None:
        self.grid[(r, c)] = Cell(r=r, c=c, v=v, f=f)

    def fill(self, rows: list[list[CellValue | None]], r0: int = 0, c0: int = 0) -> None:
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                if v is not None:
                    self.put(r0 + i, c0 + j, v)

    def snapshot(self) -> dict[tuple[int, int], Cell]:
        return {k: v.model_copy(deep=True) for k, v in self.grid.items()}

    def rng(self, r0: int, c0: int, r1: int, c1: int) -> Range:
        return Range(sheet_id=self.sheet_id, r0=r0, c0=c0, r1=r1, c1=c1)

    # -- ExecContext
    def read_range(self, rng: Range) -> list[list[Cell | None]]:
        self.reads += 1
        return [[self.grid.get((r, c)) for c in range(rng.c0, rng.c1 + 1)] for r in range(rng.r0, rng.r1 + 1)]

    def write_range(self, rng: Range, rows: list[list[CellValue | None]]) -> Delta:
        self.writes += 1
        before: list[Cell] = []
        after: list[Cell] = []
        for r in range(rng.r0, rng.r1 + 1):
            for c in range(rng.c0, rng.c1 + 1):
                i, j = r - rng.r0, c - rng.c0
                new = rows[i][j] if i < len(rows) and j < len(rows[i]) else None
                old = self.grid.get((r, c))
                old_v = None if old is None else old.v
                if old is None and new is None:
                    continue
                if old is not None and old.f is None and old_v == new:
                    continue
                before.append(old if old is not None else Cell(r=r, c=c))
                after.append(Cell(r=r, c=c, v=new))
                if new is None:
                    self.grid.pop((r, c), None)
                else:
                    self.grid[(r, c)] = Cell(r=r, c=c, v=new)
        return CellPatchDelta(sheet_id=self.sheet_id, before=before, after=after)

    def table_store(self) -> Any:
        if self.store is None:
            raise NotImplementedError
        return self.store

    # -- what the engine's apply_delta does
    def apply_delta(self, delta: Delta, *, inverse: bool) -> None:
        assert isinstance(delta, CellPatchDelta)
        for cell in (delta.before if inverse else delta.after):
            if cell.v is None and cell.f is None:
                self.grid.pop((cell.r, cell.c), None)
            else:
                self.grid[(cell.r, cell.c)] = cell.model_copy(deep=True)
