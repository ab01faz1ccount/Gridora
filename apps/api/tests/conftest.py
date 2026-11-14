from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gridora_api.config import Settings
from gridora_api.main import create_app
from gridora_api.services.auth import create_user
from gridora_api.services.passwords import Hasher

T = TypeVar("T")
TEST_DB = os.environ.get(
    "GRIDORA_TEST_DATABASE_URL", "postgresql+asyncpg://gridora:gridora@localhost:5432/gridora_test"
)
API_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "correct horse battery"


def run_db(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run `fn` against the test DB on its own connection (tests are sync; the app has its own)."""

    async def go() -> T:
        engine = create_async_engine(TEST_DB, poolclass=pool.NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                result = await fn(db)
                await db.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(go())


def alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["url"] = TEST_DB
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    async def reset(db: AsyncSession) -> None:
        await db.execute(text("drop schema public cascade"))
        await db.execute(text("create schema public"))

    run_db(reset)
    command.upgrade(alembic_config(), "head")


TABLES = "audit_log, login_attempts, sessions, users"


@pytest.fixture(autouse=True)
def clean_db(migrated_db: None) -> None:
    async def wipe(db: AsyncSession) -> None:
        await db.execute(text(f"truncate {TABLES} cascade"))

    run_db(wipe)


def fast_settings(tmp_path: Path, **over: Any) -> Settings:
    base: dict[str, Any] = dict(
        env="test",
        data_root=tmp_path / "data",
        database_url=TEST_DB,
        secure_cookies=True,
        argon2_time_cost=1,
        argon2_memory_cost_kib=64,
        argon2_parallelism=1,
    )
    base.update(over)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return fast_settings(tmp_path)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # https base URL so Secure cookies round-trip. raise_server_exceptions=False: we want the
    # 500 response a real client would get.
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def make_user(settings: Settings) -> Callable[..., str]:
    hasher = Hasher(settings)

    def _make(username: str = "alice", password: str = PASSWORD, role: str = "user") -> str:
        async def go(db: AsyncSession) -> str:
            u = await create_user(db, hasher, username=username, password=password, role=role)
            return str(u.id)

        return run_db(go)

    return _make
