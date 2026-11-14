"""Request dependencies. Any route using `auth` gets session + CSRF checks automatically."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..core.errors import DomainError, request_id_of
from ..db.session import get_db
from ..services.auth import AuthContext, resolve_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"


def cookie_name(settings: Settings) -> str:
    # The __Host- prefix needs Secure + Path=/ + no Domain; only valid over HTTPS.
    return "__Host-gridora_session" if settings.secure_cookies else "gridora_session"


def client_ip(request: Request) -> str | None:
    settings: Settings = request.app.state.settings
    if settings.trust_proxy_headers:
        real = request.headers.get("x-real-ip")
        if real:
            return real[:64]
    return request.client.host if request.client else None


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def auth(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> AuthContext:
    settings: Settings = request.app.state.settings
    raw = request.cookies.get(cookie_name(settings))
    ctx = await resolve_session(db, settings, raw) if raw else None
    if ctx is None:
        raise DomainError("unauthenticated")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(sent.encode(), ctx.session.csrf_token.encode()):
            raise DomainError("forbidden", "Missing or invalid CSRF token.")
    return ctx


__all__ = ["auth", "client_ip", "cookie_name", "get_settings_dep", "request_id_of"]
