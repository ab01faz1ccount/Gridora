"""Column-chunked typed cell store (DESIGN.md §3).

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
CHUNK_BYTES = CHUNK_ROWS * 11
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
    __slots__ = ("styles", "tags", "vals")

    def __init__(self) -> None:
        self.tags = bytearray(CHUNK_ROWS)
        self.vals: array[float] = array("d", _ZERO_VALS)
        self.styles: array[int] = array("H", bytes(2 * CHUNK_ROWS))


class SheetStore:
    def __init__(self, budget: StoreBudget) -> None:
        self._budget = budget
        self.chunks: dict[int, Chunk] = {}
        self._max_row = -1
        self._max_col = -1
        self._bounds_dirty = False
        self._cells = 0

    # -- writes -------------------------------------------------------------------------------
    def put(self, r: int, c: int, tag: int, val: float, style: int = 0) -> None:
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
            self._cells += 1
        elif tag == EMPTY:
            self._budget.cells -= 1
            self._cells -= 1
            self._bounds_dirty = True
        ch.tags[i] = tag
        ch.vals[i] = val
        ch.styles[i] = style
        if tag != EMPTY:
            self._max_row = max(self._max_row, r)
            self._max_col = max(self._max_col, c)

    # -- reads --------------------------------------------------------------------------------
    def get(self, r: int, c: int) -> tuple[int, float, int]:
        ch = self.chunks.get(c * _KEY_ROWS + (r >> CHUNK_SHIFT))
        if ch is None:
            return EMPTY, 0.0, 0
        i = r & CHUNK_MASK
        return ch.tags[i], ch.vals[i], ch.styles[i]

    def reset(self) -> None:
        """Forget all content and release this store's share of the budgets."""
        self._budget.bytes_used = max(self._budget.bytes_used - len(self.chunks) * CHUNK_BYTES, 0)
        self._budget.cells = max(self._budget.cells - self._cells, 0)
        self.chunks.clear()
        self._cells = 0
        self._max_row = self._max_col = -1
        self._bounds_dirty = False

    def column_arrays(self, c: int, r0: int, r1: int) -> tuple[bytearray, array[float], array[int]]:
        """Tags, values and styles of rows r0..r1 (inclusive) of column c, empties as zeros."""
        n = r1 - r0 + 1
        tags = bytearray(n)
        vals: array[float] = array("d", bytes(8 * n))
        styles: array[int] = array("H", bytes(2 * n))
        base = c * _KEY_ROWS
        for bi in range(r0 >> CHUNK_SHIFT, (r1 >> CHUNK_SHIFT) + 1):
            ch = self.chunks.get(base + bi)
            if ch is None:
                continue
            lo = max(r0, bi << CHUNK_SHIFT)
            hi = min(r1, ((bi + 1) << CHUNK_SHIFT) - 1)
            i0, k, o = lo & CHUNK_MASK, hi - lo + 1, lo - r0
            tags[o : o + k] = ch.tags[i0 : i0 + k]
            vals[o : o + k] = ch.vals[i0 : i0 + k]
            styles[o : o + k] = ch.styles[i0 : i0 + k]
        return tags, vals, styles

    def write_column(
        self, c: int, r0: int, tags: bytes, vals: array[float], styles: array[int]
    ) -> None:
        """Overwrite rows r0..r0+len(tags)-1 of column c from arrays. The budgets are checked for the
        whole column BEFORE anything changes, so a failure leaves the store untouched."""
        n = len(tags)
        r1 = r0 + n - 1
        base = c * _KEY_ROWS
        plan: list[tuple[int, int, int, int, Chunk | None]] = []
        delta_cells = new_chunks = 0
        for bi in range(r0 >> CHUNK_SHIFT, (r1 >> CHUNK_SHIFT) + 1):
            lo = max(r0, bi << CHUNK_SHIFT)
            hi = min(r1, ((bi + 1) << CHUNK_SHIFT) - 1)
            i0, k, o = lo & CHUNK_MASK, hi - lo + 1, lo - r0
            ch = self.chunks.get(base + bi)
            new = tags[o : o + k]
            nonempty_new = k - new.count(0)
            if ch is None:
                if nonempty_new == 0 and not any(styles[o : o + k]):
                    continue
                new_chunks += 1
            else:
                delta_cells -= k - ch.tags[i0 : i0 + k].count(0)
            delta_cells += nonempty_new
            plan.append((bi, i0, k, o, ch))
        b = self._budget
        if b.cells + delta_cells > b.max_cells or b.bytes_used + new_chunks * CHUNK_BYTES > b.max_bytes:
            raise unsupported_workbook(
                "limits.cell_count_exceeded" if b.cells + delta_cells > b.max_cells else "limits.store_bytes_exceeded",
                "The workbook would exceed the allowed size.",
            )
        for bi, i0, k, o, ch in plan:
            if ch is None:
                ch = self.chunks[base + bi] = Chunk()
                b.bytes_used += CHUNK_BYTES
            ch.tags[i0 : i0 + k] = tags[o : o + k]
            ch.vals[i0 : i0 + k] = vals[o : o + k]
            ch.styles[i0 : i0 + k] = styles[o : o + k]
        b.cells += delta_cells
        self._cells += delta_cells
        self._bounds_dirty = True  # recomputed lazily by used_size()

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
    ) -> Iterator[tuple[int, int, int, float, int]]:
        """Non-empty cells of the window in row-major order: (r, c, tag, val, style)."""
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
                        yield r, c, tag, ch.vals[i], ch.styles[i]

    def row_blocks(self, ncols: int) -> Iterator[tuple[int, list[Chunk | None]]]:
        """For export: (first_row_of_block, per-column chunk or None) for every 256-row block."""
        rows, _ = self.used_size()
        for ci in range((rows + CHUNK_ROWS - 1) >> CHUNK_SHIFT):
            yield ci << CHUNK_SHIFT, [self.chunks.get(c * _KEY_ROWS + ci) for c in range(ncols)]
