from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from gridora_contracts.models import CellWindow, CompatibilityReport, Window, Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError
from ...db.models import StoredFile, WorkbookRow
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import workbooks as wb_service
from ...services.auth import AuthContext
from ..deps import auth

router = APIRouter(tags=["workbooks"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.post("/files/{id}/open", response_model=Envelope[Workbook])
async def open_file(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[Workbook]:
    """Creates or loads the working copy; returns the Workbook (its `compat` is the report)."""
    f = await get_owned(db, StoredFile, ctx.user.id, id)
    if f.kind not in ("original", "workbook"):
        raise DomainError("bad_request", "This file cannot be opened as a workbook.")
    st = request.app.state
    row = await wb_service.import_file(
        db,
        st.services,
        st.copies,
        st.layout,
        owner_id=ctx.user.id,
        file=f,
        time_limit=st.settings.import_timeout_seconds,
    )
    return ok(request, wb_service.workbook_meta(row))


@router.get("/workbooks/{id}", response_model=Envelope[Workbook])
async def get_workbook(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[Workbook]:
    return ok(request, wb_service.workbook_meta(await get_owned(db, WorkbookRow, ctx.user.id, id)))


@router.get("/workbooks/{id}/compatibility", response_model=Envelope[CompatibilityReport])
async def get_compatibility(
    id: str, request: Request, ctx: Ctx, db: Db
) -> Envelope[CompatibilityReport]:
    wb = wb_service.workbook_meta(await get_owned(db, WorkbookRow, ctx.user.id, id))
    if wb.compat is None:
        raise DomainError("not_found", "No compatibility report is available.")
    return ok(request, wb.compat)


@router.get("/workbooks/{id}/sheets/{sheet_id}/cells", response_model=Envelope[CellWindow])
async def get_cells(
    id: str,
    sheet_id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    r0: Annotated[int, Query(ge=0)],
    c0: Annotated[int, Query(ge=0)],
    rows: Annotated[int, Query(ge=1)],
    cols: Annotated[int, Query(ge=1)],
) -> Envelope[CellWindow]:
    st = request.app.state
    cap_r, cap_c = st.settings.max_window_rows, st.settings.max_window_cols
    if rows > cap_r or cols > cap_c:  # enforced here, with the configured (possibly lower) caps
        raise DomainError(
            "validation_failed",
            f"The window is limited to {cap_r} rows x {cap_c} columns.",
        )
    row = await get_owned(db, WorkbookRow, ctx.user.id, id)
    meta = wb_service.workbook_meta(row)
    if sheet_id not in {s.id for s in meta.sheets}:
        raise DomainError("not_found")
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    window = Window(row0=r0, col0=c0, rows=rows, cols=cols)
    cw = await st.copies.call(entry, st.services.engine.get_cells, entry.handle, sheet_id, window)
    return ok(request, cw)
