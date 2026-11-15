"""Gridora workbook engine. apps/api imports only `create_engine` (contracts protocols.py)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gridora_contracts.protocols import BlobStore, WorkbookEngine

from .engine import GridoraEngine

__version__ = "0.0.1"
__all__ = ["__version__", "create_engine"]


def create_engine(config: Mapping[str, Any], blobs: BlobStore | None = None) -> WorkbookEngine:
    """`blobs` (contracts 0.4.0, ADR-014) is accepted and kept; it is unused until E5b produces
    range_snapshot deltas."""
    return GridoraEngine(config, blobs)
