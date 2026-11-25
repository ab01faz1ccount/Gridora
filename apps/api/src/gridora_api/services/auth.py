"""Accounts and sessions. Raw session tokens exist only in the cookie; the DB stores SHA-256."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from gridora_contracts.models import ErrorDetail
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..core.errors import DomainError
from ..core.ratelimit import LoginLimiter, ip_key, register_key, user_key
from ..db.models import AuthSession, User
from . import audit
from .passwords import Hasher

MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 1024  # bounds argon2 work per request
_USERNAME = re.compile(r"^[\w.@-]{3,64}$")
_TOUCH_EVERY = timedelta(seconds=60)


def normalize_username(raw: str) -> str:
    return unicodedata.normalize("NFC", raw.strip())


def valid_username(name: str) -> bool:
    return bool(_USERNAME.match(name))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


async def create_user(
    db: AsyncSession, hasher: Hasher, *, username: str, password: str, role: str = "user"
) -> User:
    username = normalize_username(username)
    if not valid_username(username):
        raise ValueError("username must be 3-64 chars: letters, digits, . _ @ -")
    if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        raise ValueError(f"password must be {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} characters")
    if role not in ("user", "admin"):
        raise ValueError("role must be user or admin")
    user = User(username=username, password_hash=await hasher.hash(password), role=role)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("username already exists") from exc
    return user


async def count_users(db: AsyncSession) -> int:
    rows = (await db.execute(select(User.id).limit(1))).first()
    return 0 if rows is None else 1


def new_session(
    db: AsyncSession, settings: Settings, user: User, *, ip: str | None, user_agent: str | None
) -> tuple[AuthSession, str]:
    """A fresh server-side session; the raw token is returned once, only its hash is stored."""
    raw = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    sess = AuthSession(
        user_id=user.id,
        token_sha256=token_hash(raw),
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=settings.session_absolute_seconds),
        ip=ip,
        user_agent=(user_agent or "")[:256] or None,
    )
    db.add(sess)
    return sess, raw


_COMMON = frozenset(
    (
        "password passw0rd password1 password12 password123 1234567890 12345678910 123456789012 "
        "qwertyuiop qwerty12345 qwerty123456 iloveyou123 letmein1234 welcome1234 admin12345 "
        "administrator abc1234567 0123456789 1q2w3e4r5t 1qaz2wsx3edc asdfghjkl1 changeme123 "
        "trustno1234 gridora1234 gridora-123"
    ).split()
)
_RESERVED = frozenset(
    {"admin", "administrator", "root", "system", "support", "gridora", "null", "api"}
)


def password_problems(username: str, password: str) -> list[str]:
    """Reasons a new password is refused (empty when it is fine). Length counts characters."""
    out: list[str] = []
    if len(password) < MIN_PASSWORD_LEN:
        out.append("auth.password_too_short")
    folded = password.casefold()
    if len(password) >= MIN_PASSWORD_LEN and (
        folded in _COMMON or len(set(password)) <= 2 or folded == username.casefold()
    ):
        out.append("auth.password_common")
    return out


async def register(
    db: AsyncSession,
    settings: Settings,
    hasher: Hasher,
    limiter: LoginLimiter,
    *,
    username: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    request_id: str,
) -> tuple[User, AuthSession, str]:
    """Self-service sign-up: a plain `user` account and a first session. Every attempt counts
    against the per-IP limit (it is what keeps account creation from being scripted)."""
    if not settings.registration_enabled:
        raise DomainError(
            "forbidden",
            "Sign-up is turned off.",
            details=[ErrorDetail(code="auth.registration_disabled", message="registration off")],
        )
    keys = [register_key(ip)]
    await limiter.check(db, keys)
    await limiter.record_failure(db, keys)  # counted before the work, committed with the outcome
    name = normalize_username(username)
    problems = [] if valid_username(name) else ["auth.username_invalid"]
    problems += password_problems(name, password)
    if len(password) > MAX_PASSWORD_LEN:
        problems.append("auth.password_too_long")
    if problems:
        await db.commit()
        raise DomainError(
            "validation_failed",
            details=[ErrorDetail(code=p, path="/", message=p) for p in problems],
        )
    total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if total >= settings.max_users:
        await db.commit()
        raise DomainError(
            "operation_conflict",
            "No more accounts can be created here.",
            details=[ErrorDetail(code="auth.registration_full", message="user limit reached")],
        )
    taken = DomainError(
        "operation_conflict",
        "That username is not available.",
        details=[ErrorDetail(code="auth.username_taken", message="username not available")],
    )
    if name.casefold() in _RESERVED:
        await db.commit()
        raise taken
    try:
        user = await create_user(db, hasher, username=name, password=password)
    except ValueError:  # the only way create_user fails here is a duplicate (rolled back inside)
        await limiter.record_failure(db, keys)
        await db.commit()
        raise taken from None
    sess, raw = new_session(db, settings, user, ip=ip, user_agent=user_agent)
    audit.record(
        db,
        action="auth.register",
        outcome="success",
        actor_id=user.id,
        ip=ip,
        request_id=request_id,
    )
    await db.commit()
    return user, sess, raw


async def change_password(
    db: AsyncSession,
    hasher: Hasher,
    limiter: LoginLimiter,
    ctx: AuthContext,
    *,
    current: str,
    new: str,
    ip: str | None,
    request_id: str,
) -> None:
    """Needs the current password (a stolen session alone cannot take the account over) and ends
    every other session of the user."""
    keys = [user_key(ctx.user.username)]
    await limiter.check(db, keys)
    if not await hasher.verify(ctx.user.password_hash, current):
        await limiter.record_failure(db, keys)
        audit.record(
            db,
            action="auth.password_change",
            outcome="failure",
            actor_id=ctx.user.id,
            ip=ip,
            request_id=request_id,
        )
        await db.commit()
        raise DomainError("unauthenticated", "The current password is not right.")
    problems = password_problems(ctx.user.username, new)
    if len(new) > MAX_PASSWORD_LEN:
        problems.append("auth.password_too_long")
    if new == current:
        problems.append("auth.password_unchanged")
    if problems:
        raise DomainError(
            "validation_failed",
            details=[ErrorDetail(code=p, path="/", message=p) for p in problems],
        )
    ctx.user.password_hash = await hasher.hash(new)
    await db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == ctx.user.id, AuthSession.id != ctx.session.id
        )
    )
    await limiter.reset(db, keys[0])
    audit.record(
        db,
        action="auth.password_change",
        outcome="success",
        actor_id=ctx.user.id,
        ip=ip,
        request_id=request_id,
    )
    await db.commit()


async def login(
    db: AsyncSession,
    settings: Settings,
    hasher: Hasher,
    limiter: LoginLimiter,
    *,
    username: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    request_id: str,
    previous_token: str | None,
) -> tuple[User, AuthSession, str]:
    """Returns (user, session, raw_token). Commits in every outcome (failures are counted)."""
    name = normalize_username(username)
    keys = [user_key(name), ip_key(ip)]
    await limiter.check(db, keys)

    user = (await db.execute(select(User).where(User.username == name))).scalar_one_or_none()
    ok = await hasher.verify(user.password_hash if user else None, password)
    if not (ok and user is not None and user.is_active):
        await limiter.record_failure(db, keys)
        audit.record(db, action="auth.login", outcome="failure", ip=ip, request_id=request_id)
        await db.commit()
        raise DomainError("unauthenticated", "Invalid username or password.")

    if hasher.needs_rehash(user.password_hash):
        user.password_hash = await hasher.hash(password)
    await limiter.reset(db, keys[0])
    if previous_token:  # rotate: an old session id is never reused after login (no fixation)
        await db.execute(
            delete(AuthSession).where(AuthSession.token_sha256 == token_hash(previous_token))
        )

    sess, raw = new_session(db, settings, user, ip=ip, user_agent=user_agent)
    audit.record(
        db, action="auth.login", outcome="success", actor_id=user.id, ip=ip, request_id=request_id
    )
    await db.commit()
    return user, sess, raw


async def resolve_session(
    db: AsyncSession, settings: Settings, raw_token: str
) -> AuthContext | None:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_sha256 == token_hash(raw_token))
        )
    ).first()
    if row is None:
        return None
    sess, user = row
    idle = timedelta(seconds=settings.session_idle_seconds)
    if sess.expires_at <= now or now - sess.last_seen_at > idle or not user.is_active:
        await db.execute(delete(AuthSession).where(AuthSession.id == sess.id))
        await db.commit()
        return None
    if now - sess.last_seen_at > _TOUCH_EVERY:  # sliding idle window without a write per request
        await db.execute(
            update(AuthSession).where(AuthSession.id == sess.id).values(last_seen_at=now)
        )
        await db.commit()
    return AuthContext(user=user, session=sess)


async def logout(db: AsyncSession, ctx: AuthContext, *, ip: str | None, request_id: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.id == ctx.session.id))
    audit.record(
        db,
        action="auth.logout",
        outcome="success",
        actor_id=ctx.user.id,
        ip=ip,
        request_id=request_id,
    )
    await db.commit()


async def bootstrap_admin(db: AsyncSession, settings: Settings, hasher: Hasher) -> bool:
    """Creates the first admin from env if (and only if) there are no users yet."""
    if not (settings.bootstrap_admin_username and settings.bootstrap_admin_password):
        return False
    if await count_users(db):
        return False
    await create_user(
        db,
        hasher,
        username=settings.bootstrap_admin_username,
        password=settings.bootstrap_admin_password.get_secret_value(),
        role="admin",
    )
    audit.record(db, action="user.bootstrap_admin", outcome="success")
    await db.commit()
    return True


def new_user_id() -> uuid.UUID:
    return uuid.uuid4()
