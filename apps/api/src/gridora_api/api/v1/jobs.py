from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from gridora_contracts.models import ApiError, Job
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...db.models import JobRow
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services.auth import AuthContext
from ..deps import auth

router = APIRouter(tags=["jobs"])


def job_out(j: JobRow) -> Job:
    return Job(
        id=str(j.id),
        kind=j.kind,
        status=j.status,
        progress=j.progress,
        result_ref=j.result_ref,
        error=ApiError.model_validate(j.error_json) if j.error_json else None,
    )


@router.get("/jobs/{id}", response_model=Envelope[Job])
async def get_job(
    id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[Job]:
    return ok(request, job_out(await get_owned(db, JobRow, ctx.user.id, id)))
