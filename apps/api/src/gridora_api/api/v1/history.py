from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from gridora_contracts.models import CellsChangedResult, HistoryEntry
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError
from ...db.models import WorkbookRow
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import history as history_service
from ...services import workbooks as wb_service
from ...services.auth import AuthContext
from ..deps import auth

router = APIRouter(tags=["history"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/documents/{id}/history", response_model=Envelope[list[HistoryEntry]])
async def list_history(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Envelope[list[HistoryEntry]]:
    row = await get_owned(db, WorkbookRow, ctx.user.id, id)
    cur: int | None = None
    if cursor is not None:
        if not cursor.isdigit():
            raise DomainError("validation_failed")
        cur = int(cursor)
    entries, nxt = await history_service.list_entries(db, row.id, cur, limit)
    return ok(request, entries, next_cursor=nxt)


async def _open(request: Request, ctx: AuthContext, db: AsyncSession, id: str):  # type: ignore[no-untyped-def]
    st = request.app.state
    row = await history_service.lock_workbook(db, ctx.user.id, id)
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    return st, row, entry


@router.post("/documents/{id}/undo", response_model=Envelope[CellsChangedResult])
async def undo(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    base_seq: Annotated[int | None, Query(ge=0)] = None,
) -> Envelope[CellsChangedResult]:
    st, row, entry = await _open(request, ctx, db, id)
    return ok(request, await history_service.undo(db, st.services, st.copies, row, entry, base_seq))


@router.post("/documents/{id}/redo", response_model=Envelope[CellsChangedResult])
async def redo(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    base_seq: Annotated[int | None, Query(ge=0)] = None,
) -> Envelope[CellsChangedResult]:
    st, row, entry = await _open(request, ctx, db, id)
    return ok(request, await history_service.redo(db, st.services, st.copies, row, entry, base_seq))
