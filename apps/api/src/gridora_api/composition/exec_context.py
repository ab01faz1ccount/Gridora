"""ExecContext: the bridge that lets dataops touch sheet data without importing the engine."""

from __future__ import annotations

from gridora_contracts.models import (
    MAX_WINDOW_COLS,
    MAX_WINDOW_ROWS,
    Cell,
    CellEdit,
    CellValue,
    Delta,
    ErrorDetail,
    Range,
    Window,
)
from gridora_contracts.protocols import TableStore, WorkbookEngine, WorkbookHandle

from ..core.errors import DomainError

# Review decision Q5: one cell_patch is capped in v1; bigger writes fail with a typed error.
MAX_PATCH_CELLS = 200_000


class EngineExecContext:
    def __init__(
        self,
        engine: WorkbookEngine,
        handle: WorkbookHandle,
        *,
        user_id: str,
        workspace_id: str,
        store: TableStore,
    ) -> None:
        self._engine, self._handle, self._store = engine, handle, store
        self.user_id, self.workspace_id = user_id, workspace_id

    def read_range(self, rng: Range) -> list[list[Cell | None]]:
        """Typed cells (formulas, errors, format hints visible); empty cells are None.
        Ranges larger than the window cap are read in tiles."""
        rows, cols = rng.r1 - rng.r0 + 1, rng.c1 - rng.c0 + 1
        out: list[list[Cell | None]] = [[None] * cols for _ in range(rows)]
        for r in range(rng.r0, rng.r1 + 1, MAX_WINDOW_ROWS):
            for c in range(rng.c0, rng.c1 + 1, MAX_WINDOW_COLS):
                win = Window(
                    row0=r,
                    col0=c,
                    rows=min(MAX_WINDOW_ROWS, rng.r1 - r + 1),
                    cols=min(MAX_WINDOW_COLS, rng.c1 - c + 1),
                )
                for cell in self._engine.get_cells(self._handle, rng.sheet_id, win).cells:
                    out[cell.r - rng.r0][cell.c - rng.c0] = cell
        return out

    def write_range(self, rng: Range, rows: list[list[CellValue | None]]) -> Delta:
        """Writes VALUES only. Cells of `rng` not covered by `rows` are cleared, so a shrinking
        result is one call and one cell_patch delta."""
        height, width = rng.r1 - rng.r0 + 1, rng.c1 - rng.c0 + 1
        if height * width > MAX_PATCH_CELLS:
            raise DomainError(
                "operation_conflict",
                "This change touches too many cells to be undoable in one step.",
                details=[
                    ErrorDetail(
                        code="too_large_for_history",
                        message=f"limit is {MAX_PATCH_CELLS} cells per undoable step",
                    )
                ],
            )
        edits: list[CellEdit] = []
        for i in range(height):
            src = rows[i] if i < len(rows) else []
            for j in range(width):
                v = src[j] if j < len(src) else None
                edits.append(CellEdit(r=rng.r0 + i, c=rng.c0 + j, value=v))
        return self._engine.apply_cell_edits(self._handle, rng.sheet_id, edits)

    def table_store(self) -> TableStore:
        return self._store
