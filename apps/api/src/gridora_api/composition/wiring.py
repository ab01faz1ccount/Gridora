"""THE ONLY module allowed to import gridora_engine / gridora_dataops (checked by a test).

GRIDORA_ENGINE / GRIDORA_DATAOPS choose "stub" or "real". "real" calls exactly the fixed factories
named in contracts protocols.py and imports nothing else from those packages:
    gridora_engine.create_engine(config)
    gridora_dataops.create_executor(config)
    gridora_dataops.create_table_store(path_for)
    gridora_dataops.catalog(locale)
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridora_contracts.protocols import (
    FormattingEngine,
    OperationExecutor,
    StructureEngine,
    TableStore,
    WorkbookEngine,
)

from ..config import Settings
from ..storage.layout import StorageLayout
from .stubs import catalog_stub, engine_stub, executor_stub


class CompositionError(RuntimeError):
    """Raised at startup when a configured implementation cannot be loaded."""


@dataclass(frozen=True)
class Services:
    engine: WorkbookEngine
    executor: OperationExecutor
    table_store: TableStore
    catalog: Callable[[str], dict[str, str]]
    engine_kind: str  # "stub" | "real"
    dataops_kind: str

    @property
    def formatting_available(self) -> bool:
        return isinstance(self.engine, FormattingEngine)

    @property
    def structure_available(self) -> bool:
        return isinstance(self.engine, StructureEngine)


def _load(module: str, which: str) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise CompositionError(
            f"GRIDORA_{which}=real but the package {module!r} is not installed"
        ) from exc


def _factory(mod: Any, name: str) -> Any:
    fn = getattr(mod, name, None)
    if not callable(fn):
        raise CompositionError(f"{mod.__name__} does not export the required factory {name}()")
    return fn


def build_services(settings: Settings, layout: StorageLayout) -> Services:
    config: dict[str, Any] = {}
    if settings.engine == "real":
        engine = _factory(_load("gridora_engine", "ENGINE"), "create_engine")(config)
    else:
        engine = engine_stub.create_engine(config)
    if not isinstance(engine, WorkbookEngine):
        raise CompositionError("the engine does not implement the WorkbookEngine protocol")

    if settings.dataops == "real":
        mod = _load("gridora_dataops", "DATAOPS")
        executor = _factory(mod, "create_executor")(config)
        store = _factory(mod, "create_table_store")(layout.table_path)
        catalog = _factory(mod, "catalog")
    else:
        executor = executor_stub.create_executor(config)
        store = executor_stub.create_table_store(layout.table_path)
        catalog = catalog_stub.catalog
    if not isinstance(executor, OperationExecutor):
        raise CompositionError("the executor does not implement the OperationExecutor protocol")
    if not isinstance(store, TableStore):
        raise CompositionError("the table store does not implement the TableStore protocol")
    return Services(engine, executor, store, catalog, settings.engine, settings.dataops)
