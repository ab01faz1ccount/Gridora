"""Lazy materialization of a worksheet into a SheetStore, one 256-row block at a time."""
from __future__ import annotations

import bisect

from ..errors import GridoraEngineError, import_failed
from ..limits import Deadline
from ..model.sheet import CHUNK_ROWS, CHUNK_SHIFT
from ..model.workbook import SheetState
from ..package import xmlsafe
from .cellparse import EXCEL_COLS, CellParser, SheetCtx, parse_ref
from .sheetsource import FeatureCollector, SheetSource

_WRAP_OPEN = b"<sheetData>"
_WRAP_CLOSE = b"</sheetData>"


def dimension_cols(dim: str) -> int:
    """Column count implied by a <dimension ref="A1:D4"/> hint (0 if absent or invalid)."""
    last = dim.rsplit(":", 1)[-1]
    try:
        return min(parse_ref(last)[1] + 1, EXCEL_COLS)
    except (ValueError, OverflowError):
        return 0


class LazySheet:
    def __init__(self, source: SheetSource, ctx: SheetCtx, deadline_seconds: float | None) -> None:
        self.source = source
        self.ctx = ctx
        self._deadline_seconds = deadline_seconds
        self.parsed_blocks: set[int] = set()
        self.eager = not source.indexed
        self.fell_back = False  # True when the byte-scan index was rejected at parse time
        self._all = False
        self._sheet: SheetState | None = None

    def bind(self, sheet: SheetState) -> None:
        """Give the lazy sheet access to the edit overlay (dirty cells survive a full re-parse)."""
        self._sheet = sheet

    # -- size hints (cheap; corrected as rows are materialized) -----------------------------------
    def used_hint(self) -> tuple[int, int]:
        s = self.source
        rows = (s.row_nums[-1] + 1) if len(s.row_nums) else 0
        return rows, max(s.max_span_col, dimension_cols(s.features.dimension))

    # -- materialization ----------------------------------------------------------------------
    def ensure(self, row_lo: int, row_hi: int) -> None:
        """Make rows [row_lo, row_hi) available in the store."""
        if self._all or row_hi <= row_lo:
            return
        if self.eager:
            self.materialize_all()
            return
        for bi in range(row_lo >> CHUNK_SHIFT, ((row_hi - 1) >> CHUNK_SHIFT) + 1):
            if bi not in self.parsed_blocks:
                self._parse_block(bi)
                if self._all:
                    return

    def _parse_block(self, bi: int) -> None:
        s = self.source
        lo, hi = bi * CHUNK_ROWS, (bi + 1) * CHUNK_ROWS
        a = bisect.bisect_left(s.row_nums, lo)
        b = bisect.bisect_left(s.row_nums, hi)
        if a == b:
            self.parsed_blocks.add(bi)
            return
        data = _WRAP_OPEN + s.slice(s.row_starts[a], s.row_end(b - 1)) + _WRAP_CLOSE
        parser = CellParser(self.ctx)
        try:
            xmlsafe.parse(
                data, start=parser.start, end=parser.end, chars=parser.chars,
                max_depth=self.ctx.limits.max_xml_depth,
            )
            ok = parser.rows_seen == list(s.row_nums[a:b])
        except GridoraEngineError as e:
            if e.reason not in ("xml.malformed", "sheet.bad_row", "sheet.bad_cell_reference"):
                raise
            ok = False
        if not ok:
            self.fell_back = True
            self.materialize_all()
            return
        self.parsed_blocks.add(bi)

    def materialize_all(self) -> None:
        """Safe full parse of the whole part (also the fallback when the index is not trusted)."""
        if self._all:
            return
        overlay = self._capture_overlay()
        self._reset_store()
        deadline = Deadline(self._deadline_seconds)
        parser = CellParser(self.ctx)
        collector = FeatureCollector()
        in_data = 0

        def start(name: str, attrs: dict[str, str]) -> None:
            nonlocal in_data
            if in_data:
                in_data += 1
                parser.start(name, attrs)
            elif xmlsafe.local(name) == "sheetData":
                in_data = 1
            else:
                collector.start(name, attrs)

        def end(name: str) -> None:
            nonlocal in_data
            if in_data:
                in_data -= 1
                if in_data:
                    parser.end(name)
            else:
                collector.end(name)

        def chars(text: str) -> None:
            if in_data:
                parser.chars(text)

        mm = self.source.mm
        assert mm is not None
        xmlsafe.parse(
            bytes(mm), start=start, end=end, chars=chars,
            max_depth=self.ctx.limits.max_xml_depth, deadline=deadline,
        )
        if self.eager:
            self.source.features = collector.f
        self._all = True
        self.parsed_blocks = set(range(EXCEL_BLOCKS))
        self._restore_overlay(overlay)

    def _capture_overlay(self) -> list[tuple[int, tuple[int, float, int], str | None]]:
        sh = self._sheet
        if sh is None or not sh.dirty:
            return []
        return [
            (k, sh.store.get(k >> 14, k & 0x3FFF), sh.formulas.get(k)) for k in sorted(sh.dirty)
        ]

    def _restore_overlay(
        self, overlay: list[tuple[int, tuple[int, float, int], str | None]]
    ) -> None:
        sh = self._sheet
        if sh is None:
            return
        for key, (tag, val, style), text in overlay:
            sh.store.put(key >> 14, key & 0x3FFF, tag, val, style)
            if text is None:
                sh.formulas.pop(key, None)
            else:
                sh.formulas[key] = text

    def _reset_store(self) -> None:
        self.ctx.store.reset()
        self.ctx.reset_cells()
        self.parsed_blocks.clear()

    def close(self) -> None:
        self.source.close()


EXCEL_BLOCKS = (1_048_576 >> CHUNK_SHIFT) + 1

__all__ = ["LazySheet", "import_failed"]
