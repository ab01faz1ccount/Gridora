"""Single error envelope (docs/API_CONTRACTS.md section 1).

Domain code raises DomainError(code=...). The HTTP status comes from ONE table that is checked
against gridora_contracts.ERROR_CODES by a test, so the two cannot drift silently.
No stack trace, exception text or path is ever put in a response.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from gridora_contracts.models import ApiError, ApiErrorEnvelope, ErrorDetail
from starlette.exceptions import HTTPException as StarletteHTTPException

from .middleware import SECURITY_HEADERS

log = logging.getLogger("gridora.errors")

STATUS_BY_CODE: dict[str, int] = {
    "bad_request": 400,
    "validation_failed": 400,
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "version_conflict": 409,
    "operation_conflict": 409,
    "file_too_large": 413,
    "unsupported_media_type": 415,
    "unsupported_workbook": 422,
    "import_failed": 422,
    "rate_limited": 429,
    "internal_error": 500,
}

_GENERIC_MESSAGE: dict[str, str] = {
    "bad_request": "The request is not valid.",
    "validation_failed": "The request failed validation.",
    "unauthenticated": "Authentication is required.",
    "forbidden": "You are not allowed to do this.",
    "not_found": "The resource was not found.",
    "version_conflict": "The document changed; reload and try again.",
    "operation_conflict": "The operation conflicts with the current state.",
    "file_too_large": "The file is too large.",
    "unsupported_media_type": "This file type is not supported.",
    "unsupported_workbook": "This workbook is not supported.",
    "import_failed": "The file could not be imported.",
    "rate_limited": "Too many requests; try again later.",
    "internal_error": "An internal error occurred.",
}


class DomainError(Exception):
    """Typed error with a stable contract `code`. `message` must be safe to show to a client."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: Sequence[ErrorDetail] = (),
        headers: dict[str, str] | None = None,
    ) -> None:
        if code not in STATUS_BY_CODE:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(code)
        self.code = code
        self.message = message or _GENERIC_MESSAGE[code]
        self.details = list(details)
        self.headers = headers or {}

    @property
    def status_code(self) -> int:
        return STATUS_BY_CODE[self.code]


def request_id_of(request: Request) -> str:
    state: Any = request.scope.get("state") or {}
    rid = state.get("request_id") if isinstance(state, dict) else getattr(state, "request_id", None)
    return str(rid) if rid else "unknown"


def error_response(
    request: Request,
    code: str,
    message: str,
    *,
    status: int | None = None,
    details: Sequence[ErrorDetail] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    env = ApiErrorEnvelope(
        error=ApiError(
            code=code, message=message, details=list(details), request_id=request_id_of(request)
        )
    )
    resp = JSONResponse(
        env.model_dump(mode="json", exclude_none=True),
        status_code=status if status is not None else STATUS_BY_CODE[code],
        headers=headers,
    )
    resp.headers["X-Request-ID"] = request_id_of(request)
    # The 500 handler runs outside RequestContextMiddleware, so set the headers here as well.
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


def _pointer(loc: Sequence[Any]) -> str:
    """JSON pointer for a pydantic error location. Body errors are relative to the body."""
    parts = [str(p) for p in loc]
    if parts and parts[0] == "body":
        parts = parts[1:]
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


async def _domain_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(DomainError, exc)
    return error_response(
        request, exc.code, exc.message, details=exc.details, headers=exc.headers or None
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    details = [
        ErrorDetail(
            code=f"validation.{e.get('type', 'invalid')}",
            path=_pointer(e["loc"]),
            message=str(e.get("msg", "Invalid value")),
        )
        for e in exc.errors()
    ]
    return error_response(
        request, "validation_failed", _GENERIC_MESSAGE["validation_failed"], details=details
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    if exc.status_code == 404:
        return error_response(request, "not_found", _GENERIC_MESSAGE["not_found"])
    if exc.status_code == 405:
        # The contract has no dedicated code; keep the real 405 status with the generic code.
        return error_response(
            request,
            "bad_request",
            "Method not allowed.",
            status=405,
            headers=dict(exc.headers or {}),
        )
    if exc.status_code == 401:
        return error_response(request, "unauthenticated", _GENERIC_MESSAGE["unauthenticated"])
    if exc.status_code == 403:
        return error_response(request, "forbidden", _GENERIC_MESSAGE["forbidden"])
    if exc.status_code >= 500:
        return error_response(request, "internal_error", _GENERIC_MESSAGE["internal_error"])
    return error_response(
        request, "bad_request", _GENERIC_MESSAGE["bad_request"], status=exc.status_code
    )


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Logged server-side with the request id; the client only gets the generic envelope.
    log.error(
        "unhandled exception request_id=%s type=%s",
        request_id_of(request),
        type(exc).__name__,
        exc_info=exc,
    )
    return error_response(request, "internal_error", _GENERIC_MESSAGE["internal_error"])


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
