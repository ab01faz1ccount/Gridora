"""Charts (contract ChartSpec): definitions per document, data computed on demand."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from gridora_contracts.models import ChartData, ChartSpec
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...db.session import get_db
from ...services import charts as chart_service
from ...services.auth import AuthContext
from ..deps import auth

router = APIRouter(tags=["charts"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/documents/{id}/charts", response_model=Envelope[list[ChartSpec]])
async def list_charts(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[list[ChartSpec]]:
    return ok(request, await chart_service.list_charts(db, ctx.user.id, id))


@router.post("/documents/{id}/charts", status_code=201, response_model=Envelope[ChartSpec])
async def create_chart(
    id: str, body: ChartSpec, request: Request, ctx: Ctx, db: Db
) -> Envelope[ChartSpec]:
    """The path decides the document; `document_id` in the body is ignored."""
    return ok(request, await chart_service.create_chart(db, ctx.user.id, id, body))


@router.put("/charts/{id}", response_model=Envelope[ChartSpec])
async def update_chart(
    id: str, body: ChartSpec, request: Request, ctx: Ctx, db: Db
) -> Envelope[ChartSpec]:
    return ok(request, await chart_service.update_chart(db, ctx.user.id, id, body))


@router.delete("/charts/{id}", status_code=204)
async def delete_chart(id: str, ctx: Ctx, db: Db) -> None:
    await chart_service.delete_chart(db, ctx.user.id, id)


@router.get("/charts/{id}/data", response_model=Envelope[ChartData])
async def chart_data(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[ChartData]:
    """The aggregated dataset for rendering (plain values; the web app maps it to ECharts)."""
    return ok(request, await chart_service.chart_data(db, request.app.state, ctx.user.id, id))
