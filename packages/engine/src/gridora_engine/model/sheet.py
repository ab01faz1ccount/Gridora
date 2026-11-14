"""Column-chunked typed cell store (PLAN.md §3).

Each (column, 256-row block) is a Chunk: 1 tag byte + 1 float64 per slot. Tags: see values.py.
A float64 holds a number, a bool (0/1), a string-table index or an error index depending on the
tag (string indices are exact up to 2**53). Chunks are allocated lazily and charged against a
byte budget, so a hostile sparse sheet cannot allocate unbounded memory.
"""
from __future__ import annotations

from array import array
from collections.abc import Iterator

from ..errors import unsupported_workbook
from .values import EMPTY

CHUNK_SHIFT = 8
CHUNK_ROWS = 1 << CHUNK_SHIFT
CHUNK_MASK = CHUNK_ROWS - 1
_KEY_ROWS = 1 << 12  # 4096 chunks * 256 rows >= 1,048,576 rows
CHUNK_BYTES = CHUNK_ROWS * 9
_ZERO_VALS = bytes(8 * CHUNK_ROWS)


class StoreBudget:
    """Shared by all sheets of a workbook."""

    def __init__(self, max_bytes: int, max_cells: int) -> None:
        self.max_bytes = max_bytes
        self.max_cells = max_cells
        self.bytes_used = 0
        self.cells = 0

    def charge_chunk(self) -> None:
        self.bytes_used += CHUNK_BYTES
        if self.bytes_used > self.max_bytes:
            raise unsupported_workbook(
                "limits.store_bytes_exceeded", "The sheet needs more memory than is allowed."
            )

    def add_cell(self) -> None:
        self.cells += 1
        if self.cells > self.max_cells:
            raise unsupported_workbook(
                "limits.cell_count_exceeded", "The workbook has more cells than is allowed."
            )


class Chunk:
    __slots__ = ("tags", "vals")

    def __init__(self) -> None:
        self.tags = bytearray(CHUNK_ROWS)
        self.vals: array[float] = array("d", _ZERO_VALS)


class SheetStore:
    def __init__(self, budget: StoreBudget) -> None:
        self._budget = budget
        self.chunks: dict[int, Chunk] = {}
        self._max_row = -1
        self._max_col = -1
        self._bounds_dirty = False

    # -- writes -------------------------------------------------------------------------------
    def put(self, r: int, c: int, tag: int, val: float) -> None:
        key = c * _KEY_ROWS + (r >> CHUNK_SHIFT)
        ch = self.chunks.get(key)
        if ch is None:
            if tag == EMPTY:
                return
            self._budget.charge_chunk()
            ch = self.chunks[key] = Chunk()
        i = r & CHUNK_MASK
        old = ch.tags[i]
        if old == EMPTY:
            if tag == EMPTY:
                return
            self._budget.add_cell()
        elif tag == EMPTY:
            self._budget.cells -= 1
            self._bounds_dirty = True
        ch.tags[i] = tag
        ch.vals[i] = val
        if tag != EMPTY:
            self._max_row = max(self._max_row, r)
            self._max_col = max(self._max_col, c)

    # -- reads --------------------------------------------------------------------------------
    def get(self, r: int, c: int) -> tuple[int, float]:
        ch = self.chunks.get(c * _KEY_ROWS + (r >> CHUNK_SHIFT))
        if ch is None:
            return EMPTY, 0.0
        i = r & CHUNK_MASK
        return ch.tags[i], ch.vals[i]

    def used_size(self) -> tuple[int, int]:
        """(row_count, col_count) of the used range; (0, 0) for an empty sheet."""
        if self._bounds_dirty:
            self._recompute_bounds()
        return self._max_row + 1, self._max_col + 1

    def _recompute_bounds(self) -> None:
        max_r = max_c = -1
        for key, ch in self.chunks.items():
            c, ci = divmod(key, _KEY_ROWS)
            for i in range(CHUNK_ROWS - 1, -1, -1):
                if ch.tags[i] != EMPTY:
                    max_r = max(max_r, (ci << CHUNK_SHIFT) + i)
                    max_c = max(max_c, c)
                    break
        self._max_row, self._max_col = max_r, max_c
        self._bounds_dirty = False

    def window(
        self, row0: int, col0: int, rows: int, cols: int
    ) -> Iterator[tuple[int, int, int, float]]:
        """Non-empty cells of the window in row-major order: (r, c, tag, val)."""
        row_end = row0 + rows
        by_col: list[tuple[int, list[Chunk | None]]] = []
        ci0, ci1 = row0 >> CHUNK_SHIFT, (row_end - 1) >> CHUNK_SHIFT
        for c in range(col0, col0 + cols):
            base = c * _KEY_ROWS
            lst = [self.chunks.get(base + ci) for ci in range(ci0, ci1 + 1)]
            if any(x is not None for x in lst):
                by_col.append((c, lst))
        for r in range(row0, row_end):
            ci = (r >> CHUNK_SHIFT) - ci0
            i = r & CHUNK_MASK
            for c, lst in by_col:
                ch = lst[ci]
                if ch is not None:
                    tag = ch.tags[i]
                    if tag != EMPTY:
                        yield r, c, tag, ch.vals[i]

    def row_blocks(self, ncols: int) -> Iterator[tuple[int, list[Chunk | None]]]:
        """For export: (first_row_of_block, per-column chunk or None) for every 256-row block."""
        rows, _ = self.used_size()
        for ci in range((rows + CHUNK_ROWS - 1) >> CHUNK_SHIFT):
            yield ci << CHUNK_SHIFT, [self.chunks.get(c * _KEY_ROWS + ci) for c in range(ncols)]
