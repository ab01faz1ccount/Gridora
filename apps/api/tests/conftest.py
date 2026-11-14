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


TABLES = "audit_log, login_attempts, jobs, workbooks, documents, files, workspaces, sessions, users"


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


class ScanningClient(TestClient):
    """TestClient that fails the test if ANY response leaks a server path (SECURITY_MODEL).

    Scans every response header, and every JSON body. Binary downloads are user content and are
    only checked through their headers.
    """

    forbidden: list[str] = []

    def request(self, *args: Any, **kwargs: Any) -> Any:
        resp = super().request(*args, **kwargs)
        hay = [f"{k}: {v}" for k, v in resp.headers.items()]
        if "json" in resp.headers.get("content-type", ""):
            hay.append(resp.text)
        for text_ in hay:
            for bad in self.forbidden:
                assert bad not in text_, f"server path/storage detail leaked in a response: {bad!r}"
        return resp


def forbidden_fragments(settings: Settings) -> list[str]:
    root = settings.data_root
    return [str(root), str(root.resolve()), "/users/", "quarantine", "storage_key", ".xlsx.tmp"]


@pytest.fixture
def make_client(app: FastAPI, settings: Settings) -> Iterator[Callable[[], ScanningClient]]:
    """The FIRST client of a test runs the app lifespan (job runner, working copies). Later
    clients share the same app without a second lifespan, so there is exactly one dispatcher,
    as in production; their requests still run normally."""
    opened: list[ScanningClient] = []
    entered: list[ScanningClient] = []

    def _make() -> ScanningClient:
        c = ScanningClient(app, base_url="https://testserver", raise_server_exceptions=False)
        c.forbidden = forbidden_fragments(settings)
        if not entered:
            c.__enter__()
            entered.append(c)
        opened.append(c)
        return c

    yield _make
    for c in entered:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[[], ScanningClient]) -> ScanningClient:
    return make_client()


@pytest.fixture
def make_user(settings: Settings) -> Callable[..., str]:
    hasher = Hasher(settings)

    def _make(username: str = "alice", password: str = PASSWORD, role: str = "user") -> str:
        async def go(db: AsyncSession) -> str:
            u = await create_user(db, hasher, username=username, password=password, role=role)
            return str(u.id)

        return run_db(go)

    return _make


class Session:
    """A logged-in client that sends its CSRF token automatically."""

    def __init__(self, client: ScanningClient, user_id: str, csrf: str) -> None:
        self.client, self.user_id = client, user_id
        client.headers["X-CSRF-Token"] = csrf

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)


@pytest.fixture
def login_as(
    make_client: Callable[[], ScanningClient], make_user: Callable[..., str]
) -> Callable[[str], Session]:
    def _login(username: str) -> Session:
        uid = make_user(username)
        c = make_client()
        r = c.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return Session(c, uid, r.json()["data"]["csrf_token"])

    return _login


@pytest.fixture
def alice(login_as: Callable[[str], Session]) -> Session:
    return login_as("alice")


@pytest.fixture
def bob(login_as: Callable[[str], Session]) -> Session:
    return login_as("bob")


def make_user_direct(username: str, password: str = PASSWORD) -> str:
    """Create a user without an app (used when a test must act BEFORE the app starts)."""
    hasher = Hasher(fast_settings(Path("unused")))

    async def go(db: AsyncSession) -> str:
        return str((await create_user(db, hasher, username=username, password=password)).id)

    return run_db(go)
