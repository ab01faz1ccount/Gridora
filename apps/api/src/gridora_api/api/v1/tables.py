"""Data Tables (contract 0.6.2): list/create/get, paged rows, and creation from a sheet range."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from gridora_contracts.models import (
    CreateTableRequest,
    DataTable,
    FromRangeRequest,
    TablePreview,
    TableRows,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...db.models import DataTableRow, Workspace
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import tables as table_service
from ...services.auth import AuthContext
from ..deps import auth

router = APIRouter(tags=["tables"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/workspaces/{id}/tables", response_model=Envelope[list[DataTable]])
async def list_tables(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[list[DataTable]]:
    w = await get_owned(db, Workspace, ctx.user.id, id)
    return ok(request, await table_service.list_tables(db, ctx.user.id, w.id))


@router.post("/workspaces/{id}/tables", status_code=201, response_model=Envelope[DataTable])
async def create_table(
    id: str, body: CreateTableRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[DataTable]:
    w = await get_owned(db, Workspace, ctx.user.id, id)
    dt = await table_service.create_table(db, request.app.state, ctx.user.id, w.id, body)
    return ok(request, dt)


@router.post("/tables/from-range", response_model=Envelope[DataTable | TablePreview])
async def table_from_range(
    body: FromRangeRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[DataTable | TablePreview]:
    """preview=true answers a TablePreview and stores nothing; otherwise a snapshot table."""
    res = await table_service.from_range(db, request.app.state, ctx.user.id, body)
    return ok(request, res)


@router.get("/tables/{id}", response_model=Envelope[DataTable])
async def get_table(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[DataTable]:
    return ok(request, table_service.table_out(await get_owned(db, DataTableRow, ctx.user.id, id)))


@router.get("/tables/{id}/rows", response_model=Envelope[TableRows])
async def get_rows(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=table_service.MAX_PAGE)] = 100,
    sort: Annotated[str | None, Query(max_length=300)] = None,
) -> Envelope[TableRows]:
    """`sort`: a column name, or `-name` for descending (Persian-aware text order)."""
    res = await table_service.read_rows(
        db, request.app.state, ctx.user.id, id, offset, limit, sort
    )
    return ok(request, res)
