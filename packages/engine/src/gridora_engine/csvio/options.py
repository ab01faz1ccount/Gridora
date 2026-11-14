from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CsvImportOptions:
    """Concrete implementation of the contracts CsvOptions protocol."""

    delimiter: str | None = None  # None = detect
    encoding: str | None = None  # None = detect
    has_header: bool = True  # informational: the engine is a grid, row 0 is just row 0
    infer_types: bool = True
