"""gridora_dataops: operations, pipelines and Data Tables.

apps/api imports ONLY these entry points (contract v0.2): create_executor, create_table_store, catalog.
"""
from .catalog import catalog
from .discovery import SearchHit, example, keywords, search_operations
from .effects import EffectSummary, apply_label, done_label, effect_lines, format_number
from .executor import DataOpsExecutor, create_executor
from .table_store import create_table_store
from .tables.store import ParquetTableStore

__all__ = [
    "DataOpsExecutor",
    "EffectSummary",
    "ParquetTableStore",
    "SearchHit",
    "apply_label",
    "catalog",
    "create_executor",
    "create_table_store",
    "done_label",
    "effect_lines",
    "example",
    "format_number",
    "keywords",
    "search_operations",
]
__version__ = "0.0.1"
