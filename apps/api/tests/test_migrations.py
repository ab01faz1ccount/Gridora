from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from gridora_api.db import models  # noqa: F401
from gridora_api.db.base import Base

from .conftest import TEST_DB, alembic_config


def test_models_match_migrations() -> None:
    """Fails if a model changes without a migration (or the migration drifts from the models)."""
    sync_url = TEST_DB.replace("+asyncpg", "+psycopg2")
    try:
        engine = create_engine(sync_url)
        conn = engine.connect()
    except ModuleNotFoundError:
        import asyncio

        from sqlalchemy.ext.asyncio import create_async_engine

        async def diff() -> list[object]:
            eng = create_async_engine(TEST_DB)
            async with eng.connect() as aconn:
                return await aconn.run_sync(
                    lambda sc: compare_metadata(MigrationContext.configure(sc), Base.metadata)
                )

        assert asyncio.run(diff()) == []
        return
    with conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_downgrade_and_upgrade_again() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
