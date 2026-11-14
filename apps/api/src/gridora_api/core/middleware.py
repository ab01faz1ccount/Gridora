"""Pure-ASGI middleware: request id, security headers, access log (no query strings)."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("gridora.access")
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # API responses are JSON or downloads; they never need to load anything.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for k, v in scope.get("headers", []):
            if k == b"x-request-id":
                cand = v.decode("latin-1")
                incoming = cand if _SAFE_ID.match(cand) else None
                break
        rid = incoming or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = rid
                for k, v in SECURITY_HEADERS.items():
                    headers.setdefault(k, v)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request_id=%s method=%s path=%s status=%s ms=%.1f",
                rid,
                scope.get("method"),
                scope.get("path"),
                status,
                (time.perf_counter() - started) * 1000,
            )
            request_id_var.reset(token)
