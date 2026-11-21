from __future__ import annotations

import asyncio
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from gridora_contracts.models import (
    CellPatchDelta,
    CellsChangedResult,
    ErrorDetail,
    Job,
    Operation,
    OperationDescriptor,
    OperationRequest,
    PreviewResult,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError, request_id_of
from ...db.models import HistoryRow, JobRow, WorkbookRow
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import history as history_service
from ...services import operations as ops_service
from ...services.auth import AuthContext
from ..deps import auth
from .jobs import job_out

router = APIRouter(tags=["operations"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/operations", response_model=Envelope[list[OperationDescriptor]])
async def list_operations(request: Request, ctx: Ctx) -> Envelope[list[OperationDescriptor]]:
    return ok(request, request.app.state.services.executor.describe_all())


@router.get("/operations/i18n", response_model=Envelope[dict[str, str]])
async def operations_i18n(
    request: Request, ctx: Ctx, locale: Annotated[str, Query(pattern="^[a-zA-Z-]{2,10}$")] = "fa"
) -> Envelope[dict[str, str]]:
    """Flat key -> text for operation labels, descriptions and categories."""
    return ok(request, request.app.state.services.catalog(locale))


@router.post("/documents/{id}/operations/preview", response_model=Envelope[PreviewResult])
async def preview_operation(
    id: str, body: Operation, request: Request, ctx: Ctx, db: Db
) -> Envelope[PreviewResult]:
    return ok(request, await ops_service.preview(db, request.app.state, ctx.user.id, id, body))


@router.post(
    "/documents/{id}/operations",
    response_model=Envelope[CellsChangedResult],
    responses={202: {"model": Envelope[Job], "description": "Still running: poll GET /jobs/{id}"}},
)
async def apply_operation(id: str, body: OperationRequest, request: Request, ctx: Ctx, db: Db):  # type: ignore[no-untyped-def]
    """Always a job, so a heavy operation never holds this request open. A fast one finishes
    within `operation_inline_seconds` and answers 200 like a cell edit; a slow one answers 202."""
    st = request.app.state
    await get_owned(db, WorkbookRow, ctx.user.id, id)  # 404 for foreign ids, before anything else
    # cheap, data-independent checks fail fast (the job re-checks everything under the lock)
    desc = ops_service.descriptor_for(st.services, body.operation.type)
    ops_service.check_confirmation(desc, body.confirm_destructive)
    job_id = await st.runner.submit(
        db,
        ctx.user.id,
        "operation",
        {
            "doc_id": id,
            "request": body.model_dump(mode="json"),
            "request_id": request_id_of(request),
        },
    )
    await db.commit()

    deadline = time.monotonic() + st.settings.operation_inline_seconds
    while True:
        async with st.sessionmaker() as sdb:
            job = (await sdb.execute(select(JobRow).where(JobRow.id == job_id))).scalar_one()
            if job.status == "succeeded":
                return ok(request, await _result_from_job(sdb, id, int(job.result_ref or 0)))
            if job.status == "failed":
                raise _error_from_job(job)
            out = job_out(job)
        if time.monotonic() >= deadline:
            return JSONResponse(
                status_code=202, content=ok(request, out).model_dump(mode="json", exclude_none=True)
            )
        await asyncio.sleep(0.05)


async def _result_from_job(db: AsyncSession, doc_id: str, seq: int) -> CellsChangedResult:
    h = (
        await db.execute(
            select(HistoryRow).where(
                HistoryRow.document_id == uuid.UUID(doc_id), HistoryRow.seq == seq
            )
        )
    ).scalar_one()
    entry = history_service.entry_out(h)
    delta = entry.delta
    cells = list(delta.after) if isinstance(delta, CellPatchDelta) else []
    sheet = delta.sheet_id if isinstance(delta, CellPatchDelta) else ""
    return CellsChangedResult(
        history_entry=entry, sheet_id=sheet, cells=cells, others=history_service.others_of(delta)
    )


def _error_from_job(job: JobRow) -> DomainError:
    e = job.error_json or {}
    return DomainError(
        str(e.get("code", "internal_error")),
        str(e.get("message", "")) or None,
        details=[ErrorDetail.model_validate(d) for d in e.get("details", [])],
    )
