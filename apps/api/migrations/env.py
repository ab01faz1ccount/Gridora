"""Async Alembic environment. URL: config attribute `url` (tests) or Settings.database_url."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from gridora_api.config import get_settings
from gridora_api.db import models  # noqa: F401  (register tables on Base.metadata)
from gridora_api.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return str(config.attributes.get("url") or get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        # One migration at a time even if two containers start together.
        context.execute("select pg_advisory_xact_lock(727274)")
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
