from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from gridora_contracts.models import AuthResult, User
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings
from ...core.envelope import Envelope, ok
from ...core.errors import request_id_of
from ...db.session import get_db
from ...services import auth as auth_service
from ..deps import auth, client_ip, cookie_name

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=auth_service.MAX_PASSWORD_LEN)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=auth_service.MAX_PASSWORD_LEN + 1)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=auth_service.MAX_PASSWORD_LEN)
    new_password: str = Field(min_length=1, max_length=auth_service.MAX_PASSWORD_LEN + 1)


class AuthConfig(BaseModel):
    registration_enabled: bool
    password_min_length: int


def _auth_result(ctx: auth_service.AuthContext) -> AuthResult:
    return AuthResult(
        user=User(id=str(ctx.user.id), username=ctx.user.username, role=ctx.user.role),
        csrf_token=ctx.session.csrf_token,
    )


@router.post("/login", response_model=Envelope[AuthResult])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[AuthResult]:
    settings: Settings = request.app.state.settings
    state = request.app.state
    user, sess, raw = await auth_service.login(
        db,
        settings,
        state.hasher,
        state.limiter,
        username=body.username,
        password=body.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id_of(request),
        previous_token=request.cookies.get(cookie_name(settings)),
    )
    response.set_cookie(
        cookie_name(settings),
        raw,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )
    return ok(request, _auth_result(auth_service.AuthContext(user=user, session=sess)))


def _set_session_cookie(response: Response, settings: Settings, raw: str) -> None:
    response.set_cookie(
        cookie_name(settings),
        raw,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )


@router.get("/config", response_model=Envelope[AuthConfig])
async def auth_config(request: Request) -> Envelope[AuthConfig]:
    """What the sign-in page needs to know before anyone is signed in."""
    settings: Settings = request.app.state.settings
    return ok(
        request,
        AuthConfig(
            registration_enabled=settings.registration_enabled,
            password_min_length=auth_service.MIN_PASSWORD_LEN,
        ),
    )


@router.post("/register", status_code=201, response_model=Envelope[AuthResult])
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[AuthResult]:
    """Create an account and sign it in. Always a plain user; admins are made on the server."""
    settings: Settings = request.app.state.settings
    state = request.app.state
    user, sess, raw = await auth_service.register(
        db,
        settings,
        state.hasher,
        state.limiter,
        username=body.username,
        password=body.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id_of(request),
    )
    _set_session_cookie(response, settings, raw)
    return ok(request, _auth_result(auth_service.AuthContext(user=user, session=sess)))


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    request: Request,
    ctx: Annotated[auth_service.AuthContext, Depends(auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Change the password; every other session of this account is ended."""
    state = request.app.state
    await auth_service.change_password(
        db,
        state.hasher,
        state.limiter,
        ctx,
        current=body.current_password,
        new=body.new_password,
        ip=client_ip(request),
        request_id=request_id_of(request),
    )
    return Response(status_code=204)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    ctx: Annotated[auth_service.AuthContext, Depends(auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    settings: Settings = request.app.state.settings
    await auth_service.logout(db, ctx, ip=client_ip(request), request_id=request_id_of(request))
    resp = Response(status_code=204)
    resp.delete_cookie(
        cookie_name(settings),
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    return resp


@router.get("/me", response_model=Envelope[AuthResult])
async def me(
    request: Request, ctx: Annotated[auth_service.AuthContext, Depends(auth)]
) -> Envelope[AuthResult]:
    return ok(request, _auth_result(ctx))
