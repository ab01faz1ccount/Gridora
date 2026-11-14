"""Postgres-backed job runner (PLAN 2.7): a `jobs` table plus an in-process dispatcher.

JobRunner is the interface; PostgresJobRunner is the v1 implementation. A separate worker process
can implement the same interface later. Jobs are claimed with FOR UPDATE SKIP LOCKED, so two
dispatchers (or processes) never run the same job.

Crash recovery: at startup, jobs left `running` by a dead process are marked failed
(`internal_error`), NOT silently retried: imports/operations are not guaranteed idempotent.
Queued jobs simply run.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from gridora_contracts.models import ApiError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.errors import DomainError
from ..db.models import JobRow

log = logging.getLogger("gridora.jobs")

Handler = Callable[[JobRow], Awaitable[str | None]]  # returns result_ref


class JobRunner(Protocol):
    async def submit(
        self, db: AsyncSession, owner_id: uuid.UUID, kind: str, payload: dict[str, Any]
    ) -> uuid.UUID: ...


def _now() -> datetime:
    return datetime.now(UTC)


class PostgresJobRunner:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        handlers: dict[str, Handler],
        *,
        poll_interval: float = 0.5,
        max_concurrent: int = 2,
    ) -> None:
        self._sm, self._handlers = sessionmaker, handlers
        self._poll, self._sem = poll_interval, asyncio.Semaphore(max_concurrent)
        self._task: asyncio.Task[None] | None = None
        self._running: set[asyncio.Task[None]] = set()

    async def submit(
        self, db: AsyncSession, owner_id: uuid.UUID, kind: str, payload: dict[str, Any]
    ) -> uuid.UUID:
        """Inserts a queued job in the CALLER's transaction (committed with the upload)."""
        job = JobRow(owner_id=owner_id, kind=kind, status="queued", payload=payload)
        db.add(job)
        await db.flush()
        return job.id

    # ------------------------------------------------------------ lifecycle ----
    async def start(self) -> None:
        async with self._sm() as db:
            res = await db.execute(
                update(JobRow)
                .where(JobRow.status == "running")
                .values(
                    status="failed",
                    finished_at=_now(),
                    error_json=_error("internal_error", "The server restarted during this job."),
                )
            )
            await db.commit()
            if res.rowcount:  # type: ignore[attr-defined]
                log.warning("marked %s interrupted job(s) failed", res.rowcount)  # type: ignore[attr-defined]
        self._task = asyncio.create_task(self._loop(), name="job-dispatcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for t in list(self._running):
            t.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)

    # ------------------------------------------------------------ dispatcher ----
    async def _loop(self) -> None:
        while True:
            await self._sem.acquire()
            try:
                job = await self._claim()
            except Exception:  # noqa: BLE001 - DB hiccup: keep the dispatcher alive
                log.exception("job claim failed")
                job = None
            if job is None:
                self._sem.release()
                await asyncio.sleep(self._poll)
                continue
            t = asyncio.create_task(self._execute(job))
            self._running.add(t)
            t.add_done_callback(self._running.discard)

    async def _claim(self) -> JobRow | None:
        async with self._sm() as db:
            job = (
                await db.execute(
                    select(JobRow)
                    .where(JobRow.status == "queued")
                    .order_by(JobRow.created_at, JobRow.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if job is None:
                return None
            job.status, job.started_at, job.attempts = "running", _now(), job.attempts + 1
            await db.commit()
            return job

    async def _execute(self, job: JobRow) -> None:
        try:
            handler = self._handlers.get(job.kind)
            if handler is None:
                raise DomainError("internal_error")
            ref = await handler(job)
            await self._finish(job.id, "succeeded", result_ref=ref)
        except DomainError as exc:
            await self._finish(
                job.id,
                "failed",
                error=_error(
                    exc.code,
                    exc.message,
                    request_id=job.payload.get("request_id"),
                    details=[d.model_dump(exclude_none=True) for d in exc.details],
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never leak internals into the job record
            log.exception("job %s crashed", job.id)
            await self._finish(
                job.id,
                "failed",
                error=_error(
                    "internal_error",
                    "An internal error occurred.",
                    request_id=job.payload.get("request_id"),
                ),
            )
        finally:
            self._sem.release()

    async def _finish(
        self,
        job_id: uuid.UUID,
        status: str,
        *,
        result_ref: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        async with self._sm() as db:
            await db.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(
                    status=status,
                    result_ref=result_ref,
                    error_json=error,
                    finished_at=_now(),
                    progress=1.0 if status == "succeeded" else None,
                )
            )
            await db.commit()


def _error(
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return ApiError(
        code=code,
        message=message,
        details=details or [],
        request_id=request_id or "job",
    ).model_dump(mode="json", exclude_none=True)
