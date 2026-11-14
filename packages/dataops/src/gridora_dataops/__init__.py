"""gridora_dataops: operations, pipelines and Data Tables.

apps/api imports ONLY these entry points (contract v0.2): create_executor, create_table_store, catalog.
"""
from .catalog import catalog
from .executor import DataOpsExecutor, create_executor
from .table_store import create_table_store

__all__ = ["DataOpsExecutor", "catalog", "create_executor", "create_table_store"]
__version__ = "0.0.1"
