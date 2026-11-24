"""Wraps a WorkbookEngine so its typed errors become API DomainErrors (no engine import needed:
the engine's errors are recognised by their attributes `code`, `reason`, `public_message`).

Optional protocols (FormattingEngine, StructureEngine, ColumnarEngine) stay detectable with
isinstance(): a wrapped method is attached to the adapter only if the engine has it.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from gridora_contracts.models import ErrorDetail
from gridora_contracts.protocols import WorkbookEngine

from ..core.errors import STATUS_BY_CODE, DomainError

OPTIONAL_METHODS = (
    "get_styles",
    "get_sheet_layout",
    "read_range_columnar",
    "write_range_columnar",
    "apply_structure_change",
    "set_calendar",
    "detect_date_columns",
    "find_cells",
    "fill_edits",
)


def translate(exc: BaseException) -> DomainError | None:
    code = getattr(exc, "code", None)
    reason = getattr(exc, "reason", None)
    message = getattr(exc, "public_message", None)
    if isinstance(code, str) and isinstance(reason, str) and isinstance(message, str):
        if reason == "too_large_for_history":  # Review 4 decision 2: top-level operation_conflict
            code = "operation_conflict"
        if code not in STATUS_BY_CODE:
            code = "internal_error"
            message = "An internal error occurred."
        return DomainError(code, message, details=[ErrorDetail(code=reason, message=message)])
    if isinstance(exc, NotImplementedError) and isinstance(getattr(exc, "method", None), str):
        return DomainError(
            "operation_conflict",
            "This engine version does not support that yet.",
            details=[ErrorDetail(code="engine.not_implemented", message=str(exc.method))],  # type: ignore[attr-defined]
        )
    return None


def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DomainError:
            raise
        except Exception as exc:
            mapped = translate(exc)
            if mapped is None:
                raise
            raise mapped from None  # fixed message only; the original is not chained to the client

    return call


class EngineErrorAdapter:
    def __init__(self, engine: WorkbookEngine) -> None:
        self._engine = engine
        for name in OPTIONAL_METHODS:
            if hasattr(engine, name):
                setattr(self, name, _wrap(getattr(engine, name)))

    @property
    def wrapped(self) -> WorkbookEngine:
        return self._engine

    def import_xlsx(self, path: Path, *, file_id: str | None = None) -> Any:
        return _wrap(self._engine.import_xlsx)(path, file_id=file_id)

    def import_csv(self, path: Path, options: Any, *, file_id: str | None = None) -> Any:
        return _wrap(self._engine.import_csv)(path, options, file_id=file_id)

    def close(self, wb: Any) -> None:
        _wrap(self._engine.close)(wb)

    def get_cells(self, wb: Any, sheet_id: str, window: Any) -> Any:
        return _wrap(self._engine.get_cells)(wb, sheet_id, window)

    def apply_cell_edits(self, wb: Any, sheet_id: str, edits: Any) -> Any:
        return _wrap(self._engine.apply_cell_edits)(wb, sheet_id, edits)

    def apply_delta(self, wb: Any, delta: Any, *, inverse: bool) -> None:
        _wrap(self._engine.apply_delta)(wb, delta, inverse=inverse)

    def recalculate(self, wb: Any) -> None:
        _wrap(self._engine.recalculate)(wb)

    def export_xlsx(self, wb: Any, path: Path) -> Any:
        return _wrap(self._engine.export_xlsx)(wb, path)

    def export_csv(self, wb: Any, sheet_id: str, path: Path) -> Any:
        return _wrap(self._engine.export_csv)(wb, sheet_id, path)
