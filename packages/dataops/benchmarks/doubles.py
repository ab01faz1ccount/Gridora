"""Lean sheet doubles for measuring the DATAOPS side of the sheet path (not an engine).

`LeanRowContext` implements only the row-major `ExecContext`; `LeanColumnarContext` adds the optional columnar protocol.
They hold the sheet as typed column lists and do no diffing and no history, so what is measured is the adapter
(cells/columns <-> Polars) plus the minimum an interface forces on any engine:

  mode "A" (adapter only): the row double hands out PREBUILT `Cell` objects and ignores the rows it is given.
  mode "B" (adapter + interface objects): the row double BUILDS a `Cell` per cell on read and PARSES the rows on write,
            which is what any engine must do to honour `list[list[Cell]]`; the columnar double just slices/stores lists.
"""
from __future__ import annotations

from typing import Any

import polars as pl
from gridora_contracts.models import (
    BoolValue,
    Cell,
    CellPatchDelta,
    ColumnarColumn,
    ColumnarRange,
    DateValue,
    NumValue,
    Range,
    StrValue,
)

_KINDS = {pl.Int64: "num", pl.Float64: "num", pl.String: "str", pl.Boolean: "bool", pl.Date: "date"}


def _cv(kind: str, v: Any) -> Any:
    if v is None:
        return None
    return {"num": lambda x: NumValue(n=float(x)), "str": StrValue.model_construct if False else (lambda x: StrValue(s=x)),
            "bool": lambda x: BoolValue(b=x), "date": lambda x: DateValue(iso=x)}[kind](v)


class LeanRowContext:
    user_id = "u1"
    workspace_id = "w1"

    def __init__(self, frame: pl.DataFrame, mode: str = "A", store: Any = None) -> None:
        self.mode = mode
        self.store = store
        self.names = list(frame.columns)
        self.kinds = [_KINDS[frame.schema[c]] for c in self.names]
        self.body: list[list[Any]] = []
        for c, k in zip(self.names, self.kinds, strict=True):
            s = frame[c]
            self.body.append([None if v is None else v.isoformat() for v in s.to_list()] if k == "date" else s.to_list())
        self.nrows = frame.height + 1  # header row + body
        self.cells: list[list[Cell | None]] | None = None
        if mode == "A":  # prebuilt once, outside any timing
            self.cells = [[Cell(r=0, c=j, v=StrValue(s=n)) for j, n in enumerate(self.names)]]
            for i in range(frame.height):
                self.cells.append([None if self.body[j][i] is None else Cell(r=i + 1, c=j, v=_cv(self.kinds[j], self.body[j][i]))
                                   for j in range(len(self.names))])
        self.written: Any = None

    def table_store(self) -> Any:
        if self.store is None:
            raise NotImplementedError
        return self.store

    def read_range(self, rng: Range) -> list[list[Cell | None]]:
        r1 = min(rng.r1, self.nrows - 1)
        if self.mode == "A":
            assert self.cells is not None
            rows = [row[rng.c0:rng.c1 + 1] for row in self.cells[rng.r0:r1 + 1]]
        else:
            rows = []
            for r in range(rng.r0, r1 + 1):
                if r == 0:
                    rows.append([Cell(r=0, c=j, v=StrValue(s=self.names[j])) for j in range(rng.c0, min(rng.c1, len(self.names) - 1) + 1)])
                else:
                    rows.append([None if self.body[j][r - 1] is None else Cell(r=r, c=j, v=_cv(self.kinds[j], self.body[j][r - 1]))
                                 for j in range(rng.c0, min(rng.c1, len(self.names) - 1) + 1)])
        width = rng.c1 - rng.c0 + 1
        rows = [row + [None] * (width - len(row)) for row in rows]
        return rows + [[None] * width for _ in range(rng.r1 - r1)]

    def write_range(self, rng: Range, rows: list[list[Any]]) -> CellPatchDelta:
        if self.mode == "B":  # an engine has to read the values out of the objects it is handed
            self.written = [[None if v is None else getattr(v, v.k[0] if v.k != "str" else "s", None) for v in row] for row in rows]
        else:
            self.written = rows
        return CellPatchDelta(sheet_id=rng.sheet_id, before=[], after=[])


class LeanColumnarContext(LeanRowContext):
    def read_range_columnar(self, rng: Range) -> ColumnarRange:
        cols = []
        for j in range(rng.c0, rng.c1 + 1):
            if j >= len(self.names) or rng.r0 >= self.nrows:
                cols.append(ColumnarColumn(kind="empty", values=[None] * (rng.r1 - rng.r0 + 1)))
            elif rng.r0 == 0 and rng.r1 == 0:
                cols.append(ColumnarColumn(kind="str", values=[self.names[j]]))
            else:
                assert rng.r0 >= 1, "the adapter reads the header row and the body separately"
                vals = self.body[j][rng.r0 - 1:rng.r1]
                vals = vals + [None] * (rng.r1 - rng.r0 + 1 - len(vals))
                cols.append(ColumnarColumn(kind=self.kinds[j], values=vals))  # type: ignore[arg-type]
        return ColumnarRange(range=rng, columns=cols, has_formulas=False)

    def write_range_columnar(self, rng: Range, data: ColumnarRange) -> CellPatchDelta:
        self.written = data.columns
        return CellPatchDelta(sheet_id=rng.sheet_id, before=[], after=[])
