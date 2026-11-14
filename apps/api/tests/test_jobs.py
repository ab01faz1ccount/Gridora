from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import pool, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gridora_api.core.errors import DomainError
from gridora_api.db.models import JobRow
from gridora_api.jobs.runner import PostgresJobRunner

from .conftest import TEST_DB, Session, run_db
from .helpers import wait_job


def insert_job(kind: str, status: str, payload: dict[str, Any] | None = None) -> str:
    async def go(db: AsyncSession) -> str:
        owner = (await db.execute(text("select id from users limit 1"))).scalar_one()
        j = JobRow(owner_id=owner, kind=kind, status=status, payload=payload or {})
        db.add(j)
        await db.flush()
        return str(j.id)

    return run_db(go)


def job_row(job_id: str) -> JobRow:
    async def go(db: AsyncSession) -> JobRow:
        return (await db.execute(select(JobRow).where(JobRow.id == uuid.UUID(job_id)))).scalar_one()

    return run_db(go)


# ------------------------------------------------------- through the HTTP app ----
def test_a_queued_job_left_by_a_previous_process_is_picked_up(alice: Session) -> None:
    jid = insert_job("import", "queued", {"file_id": str(uuid.uuid4()), "request_id": "r-1"})
    job = wait_job(alice, jid)
    assert job["status"] == "failed" and job["error"]["code"] == "import_failed"
    assert job["error"]["request_id"] == "r-1"
    assert job_row(jid).attempts == 1


def test_a_job_with_no_handler_fails_generically(alice: Session) -> None:
    job = wait_job(alice, insert_job("operation", "queued"))  # no operation handler yet
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"


def test_jobs_left_running_by_a_dead_process_are_failed_at_startup(
    login_as: Any, make_client: Any
) -> None:
    # Created BEFORE the app starts: the first client's lifespan performs the recovery.
    from .conftest import make_user_direct

    make_user_direct("zed")
    jid = insert_job("import", "running", {"file_id": str(uuid.uuid4())})
    client = make_client()  # starts the app (and the runner)
    client.post("/api/v1/auth/login", json={"username": "zed", "password": "correct horse battery"})
    job = client.get(f"/api/v1/jobs/{jid}").json()["data"]
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert "restarted" in job["error"]["message"]
    assert job_row(jid).attempts == 0  # it was never re-run


def test_unknown_job_is_404(alice: Session) -> None:
    assert alice.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404


# ----------------------------------------------- the runner on its own (async) ----
@pytest.fixture
async def sm() -> Any:
    engine = create_async_engine(TEST_DB, poolclass=pool.NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("truncate jobs, sessions, files, workspaces, users cascade"))
        await conn.execute(
            text(
                "insert into users (id, username, password_hash, role, is_active) "
                "values (:i, 'u', 'x', 'user', true)"
            ),
            {"i": uuid.uuid4()},
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def submit_many(runner: PostgresJobRunner, sm: Any, n: int) -> list[uuid.UUID]:
    async with sm() as db:
        owner = (await db.execute(text("select id from users"))).scalar_one()
        ids = [await runner.submit(db, owner, "import", {"i": i}) for i in range(n)]
        await db.commit()
    return ids


async def wait_all_done(sm: Any, n: int, seconds: float = 10) -> None:
    for _ in range(int(seconds / 0.05)):
        async with sm() as db:
            done = (
                await db.execute(
                    text("select count(*) from jobs where status in ('succeeded','failed')")
                )
            ).scalar_one()
        if done == n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("jobs did not finish")


async def test_two_dispatchers_never_run_the_same_job(sm: Any) -> None:
    seen: Counter[int] = Counter()

    async def handler(job: JobRow) -> str | None:
        seen[job.payload["i"]] += 1
        await asyncio.sleep(0.01)
        return f"done-{job.payload['i']}"

    a = PostgresJobRunner(sm, {"import": handler}, poll_interval=0.01, max_concurrent=3)
    b = PostgresJobRunner(sm, {"import": handler}, poll_interval=0.01, max_concurrent=3)
    await a.start()
    await b.start()
    try:
        await submit_many(a, sm, 30)
        await wait_all_done(sm, 30)
    finally:
        await a.stop()
        await b.stop()
    assert sorted(seen) == list(range(30)) and set(seen.values()) == {1}  # exactly once each


async def test_concurrency_limit_is_respected(sm: Any) -> None:
    running = peak = 0

    async def handler(job: JobRow) -> str | None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return None

    r = PostgresJobRunner(sm, {"import": handler}, poll_interval=0.01, max_concurrent=2)
    await r.start()
    try:
        await submit_many(r, sm, 8)
        await wait_all_done(sm, 8)
    finally:
        await r.stop()
    assert peak == 2


async def test_domain_error_and_crash_are_recorded_differently(sm: Any) -> None:
    async def handler(job: JobRow) -> str | None:
        if job.payload["i"] == 0:
            raise DomainError("import_failed", "bad file")
        raise RuntimeError("secret internals")

    r = PostgresJobRunner(sm, {"import": handler}, poll_interval=0.01)
    await r.start()
    try:
        await submit_many(r, sm, 2)
        await wait_all_done(sm, 2)
    finally:
        await r.stop()
    async with sm() as db:
        rows = (
            (await db.execute(select(JobRow).order_by(JobRow.payload["i"].astext))).scalars().all()
        )
    assert (
        rows[0].error_json["code"] == "import_failed"
        and rows[0].error_json["message"] == "bad file"
    )
    assert rows[1].error_json["code"] == "internal_error"
    assert "secret" not in str(rows[1].error_json)
    assert all(j.status == "failed" and j.finished_at is not None for j in rows)
