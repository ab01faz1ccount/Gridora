"""TableStore entry point (contract v0.2: create_table_store(path_for) -> TableStore)."""
from __future__ import annotations

from typing import Any

from .tables.store import ParquetTableStore, PathResolver


def create_table_store(path_for: PathResolver, **config: Any) -> ParquetTableStore:
    """The returned store must be bound per owner with `.for_owner(user_id)` before `read_page`/`restore_version`."""
    return ParquetTableStore(path_for, **config)
