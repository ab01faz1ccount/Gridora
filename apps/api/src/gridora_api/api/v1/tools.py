"""Saved tools (workflows): CRUD and run (a job)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from gridora_contracts.models import Job, Tool, ToolRunRequest
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError
from ...db.models import JobRow, ToolRow
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import tools as tool_service
from ...services.auth import AuthContext
from ..deps import auth
from .jobs import job_out

router = APIRouter(tags=["tools"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/tools", response_model=Envelope[list[Tool]])
async def list_tools(request: Request, ctx: Ctx, db: Db) -> Envelope[list[Tool]]:
    return ok(request, await tool_service.list_tools(db, ctx.user.id))


@router.post("/tools", status_code=201, response_model=Envelope[Tool])
async def create_tool(body: Tool, request: Request, ctx: Ctx, db: Db) -> Envelope[Tool]:
    return ok(request, await tool_service.create_tool(db, request.app.state, ctx.user.id, body))


@router.get("/tools/{id}", response_model=Envelope[Tool])
async def get_tool(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[Tool]:
    return ok(request, tool_service.tool_out(await get_owned(db, ToolRow, ctx.user.id, id)))


@router.put("/tools/{id}", response_model=Envelope[Tool])
async def update_tool(id: str, body: Tool, request: Request, ctx: Ctx, db: Db) -> Envelope[Tool]:
    res = await tool_service.update_tool(db, request.app.state, ctx.user.id, id, body)
    return ok(request, res)


@router.delete("/tools/{id}", status_code=204)
async def delete_tool(id: str, ctx: Ctx, db: Db) -> None:
    await tool_service.delete_tool(db, ctx.user.id, id)


@router.post("/tools/{id}/run", status_code=202, response_model=Envelope[Job])
async def run_tool(
    id: str, body: ToolRunRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[Job]:
    """A job like an operation: poll GET /jobs/{id}; the result is the last history seq."""
    await get_owned(db, ToolRow, ctx.user.id, id)
    job_id = await request.app.state.runner.submit(
        db,
        ctx.user.id,
        "operation",
        {"doc_id": body.workbook_id, "tool_id": id, "tool_run": body.model_dump(mode="json")},
    )
    await db.commit()
    job = await db.get(JobRow, job_id)
    if job is None:
        raise DomainError("internal_error")
    return ok(request, job_out(job))
