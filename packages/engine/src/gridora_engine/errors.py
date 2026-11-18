"""Typed engine errors.

`code` is one of contracts ERROR_CODES. `reason` is a stable engine-level sub-code
(ADR-010 / CC-8: surfaced to clients through ErrorDetail.code). `public_message` is built from
fixed templates only: it never contains filesystem paths, file names, or raw exception text.
"""
from __future__ import annotations

from gridora_contracts.models import ERROR_CODES, ErrorDetail


class GridoraEngineError(Exception):
    def __init__(self, code: str, reason: str, public_message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown contract error code: {code}")
        super().__init__(public_message)
        self.code = code
        self.reason = reason
        self.public_message = public_message

    def __str__(self) -> str:
        return self.public_message

    def to_detail(self) -> ErrorDetail:
        return ErrorDetail(code=self.reason, message=self.public_message)


class EngineNotImplementedError(NotImplementedError):
    """A contract method that this engine version does not implement yet (see PLAN.md §15)."""

    def __init__(self, method: str) -> None:
        super().__init__(f"{method} is not implemented in this engine version")
        self.method = method


def bad_request(reason: str, message: str) -> GridoraEngineError:
    return GridoraEngineError("bad_request", reason, message)


def import_failed(reason: str, message: str) -> GridoraEngineError:
    return GridoraEngineError("import_failed", reason, message)


def unsupported_workbook(reason: str, message: str) -> GridoraEngineError:
    return GridoraEngineError("unsupported_workbook", reason, message)


def file_too_large(reason: str, message: str) -> GridoraEngineError:
    return GridoraEngineError("file_too_large", reason, message)


def validation_failed(reason: str, message: str) -> GridoraEngineError:
    return GridoraEngineError("validation_failed", reason, message)


def too_large_for_history() -> GridoraEngineError:
    """Review 4 / ADR-015: top-level `operation_conflict`, detail code `too_large_for_history`
    (`to_detail().code`). apps/api maps `exc.code` to the HTTP status and `exc.to_detail()` to the detail."""
    return GridoraEngineError(
        "operation_conflict", "too_large_for_history",
        "The change is too large to be undone in one step.",
    )


operation_conflict_too_large = too_large_for_history  # readable alias for the columnar module
