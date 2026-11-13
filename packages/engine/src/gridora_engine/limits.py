"""Resource limits. Defaults follow the Phase 2 review (A1-4) and are tuned after the E1 benchmark.

Time limits are cooperative: pure Python cannot be pre-empted. Hard memory/time enforcement
needs OS-level isolation (Phase 4, ADR-011); the engine only budgets what it can count.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from gridora_contracts.models import MAX_UPLOAD_BYTES

from .errors import GridoraEngineError, bad_request

EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_COLS = 16_384
EXCEL_MAX_CELL_CHARS = 32_767


@dataclass(frozen=True)
class ResourceLimits:
    max_file_bytes: int = MAX_UPLOAD_BYTES
    max_cells: int = 5_000_000  # non-empty cells per workbook
    max_rows: int = EXCEL_MAX_ROWS
    max_cols: int = EXCEL_MAX_COLS
    max_field_chars: int = EXCEL_MAX_CELL_CHARS
    max_store_bytes: int = 2 * 1024**3  # estimated typed-array bytes allocated by the cell store
    max_compression_ratio: int = 100  # used by the zip reader (E3)
    max_uncompressed_bytes: int = 500 * 1024**2  # used by the zip reader (E3)
    max_zip_entries: int = 10_000  # used by the zip reader (E3)
    deadline_seconds: float | None = None  # cooperative wall-clock budget per call

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ResourceLimits:
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise bad_request("config.unknown_limit", "Unknown engine limit in configuration.")
        return cls(**dict(raw))


class Deadline:
    """Cooperative deadline; call check() every few thousand units of work."""

    def __init__(self, seconds: float | None) -> None:
        self._end = None if seconds is None else time.monotonic() + seconds

    def check(self) -> None:
        if self._end is not None and time.monotonic() > self._end:
            raise GridoraEngineError(
                "import_failed", "limits.deadline_exceeded",
                "Processing took longer than the allowed time.",
            )
