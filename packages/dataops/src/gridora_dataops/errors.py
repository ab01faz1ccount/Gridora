"""Typed errors and ValidationError builders.

Codes are stable strings (never renamed, only added). Messages are English defaults; the UI
translates by `code` through the i18n catalog (`errors.<code>.message`).
"""
from __future__ import annotations

from gridora_contracts.models import ValidationError

# Every code the package can emit. A test pins that each has Persian text in the catalog.
ERROR_CODES = (
    "unknown_operation",
    "unsupported_target",
    "invalid_param",
    "unknown_param",
    "unknown_column",
    "type_mismatch",
    "range_has_formulas",
    "range_has_error_values",
    "mixed_column_types",
    "would_overwrite",
    "too_large_for_history",
    "version_unavailable",
    "version_conflict",
    "owner_unknown",
    "table_not_found",
    "not_implemented",
    "pipeline_aborted",
    "rollback_incomplete",
    "result_too_large",
    "chart_too_many_categories",
    "chart_series_mismatch",
    "validation_failed",
)


def pointer(*parts: object) -> str:
    """Build a JSON pointer (RFC 6901) relative to the Operation root."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def verr(code: str, path: str, message: str, hint: str | None = None) -> ValidationError:
    return ValidationError(code=code, path=path, message=message, hint=hint)


class DataOpsError(Exception):
    """Domain error with a stable `code`. apps/api maps it to the HTTP envelope."""

    def __init__(self, code: str, message: str, *, path: str = "", hint: str | None = None,
                 errors: list[ValidationError] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors: list[ValidationError] = errors if errors is not None else [verr(code, path, message, hint)]


class NotImplementedYet(DataOpsError):
    def __init__(self, what: str) -> None:
        super().__init__("not_implemented", f"{what} is not implemented yet", path="")
