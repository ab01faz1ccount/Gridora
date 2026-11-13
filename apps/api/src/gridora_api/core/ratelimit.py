"""Login rate limiting backed by Postgres (no Redis). Keys are hashed; raw usernames never stored.

record_failure is one atomic upsert, so concurrent attempts cannot undercount.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import LoginAttempt
from .errors import DomainError


def user_key(username: str) -> str:
    return "u:" + hashlib.sha256(username.lower().encode()).hexdigest()[:64]


def ip_key(ip: str | None) -> str:
    return "i:" + hashlib.sha256((ip or "unknown").encode()).hexdigest()[:64]


class LoginLimiter:
    def __init__(self, window_seconds: int, max_user: int, max_ip: int) -> None:
        self.window = timedelta(seconds=window_seconds)
        self.limits = {"u": max_user, "i": max_ip}

    async def check(self, db: AsyncSession, keys: list[str]) -> None:
        now = datetime.now(UTC)
        rows = (await db.execute(select(LoginAttempt).where(LoginAttempt.key.in_(keys)))).scalars()
        for row in rows:
            in_window = now - row.window_start <= self.window
            if in_window and row.count >= self.limits[row.key[0]]:
                retry = max(1, math.ceil((row.window_start + self.window - now).total_seconds()))
                raise DomainError("rate_limited", headers={"Retry-After": str(retry)})

    async def record_failure(self, db: AsyncSession, keys: list[str]) -> None:
        now = datetime.now(UTC)
        cutoff = now - self.window
        for key in keys:
            stmt = pg_insert(LoginAttempt).values(key=key, window_start=now, count=1)
            expired = LoginAttempt.window_start < cutoff
            stmt = stmt.on_conflict_do_update(
                index_elements=[LoginAttempt.key],
                set_={
                    "count": case((expired, 1), else_=LoginAttempt.count + 1),
                    "window_start": case((expired, now), else_=LoginAttempt.window_start),
                },
            )
            await db.execute(stmt)
        # Keep the table small: forget windows that ended long ago.
        await db.execute(
            delete(LoginAttempt).where(LoginAttempt.window_start < now - 2 * self.window)
        )

    async def reset(self, db: AsyncSession, key: str) -> None:
        await db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
