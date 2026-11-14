"""Gridora workbook engine. apps/api imports only `create_engine` (contracts protocols.py)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gridora_contracts.protocols import WorkbookEngine

from .engine import GridoraEngine

__version__ = "0.0.1"
__all__ = ["__version__", "create_engine"]


def create_engine(config: Mapping[str, Any]) -> WorkbookEngine:
    return GridoraEngine(config)
