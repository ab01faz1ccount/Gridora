from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from gridora_contracts.models import (
    CellEditRequest,
    CellsChangedResult,
    CellWindow,
    CompatibilityReport,
    DateColumn,
    DateColumns,
    ErrorDetail,
    ExportRequest,
    FileRecord,
    FillRequest,
    FindMatch,
    FindResult,
    Job,
    SetCalendarRequest,
    Window,
    Workbook,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError
from ...db.models import JobRow, StoredFile, WorkbookRow
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import exports as exports_service
from ...services import history as history_service
from ...services import workbooks as wb_service
from ...services.auth import AuthContext
from ..deps import auth
from .jobs import job_out
from .workspaces import file_out

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
    cw = await st.copies.call(
        entry, st.services.engine.get_cells, entry.handle, entry.to_engine(sheet_id), window
    )
    # clients only ever see the public sheet id (the engine's differs after a rebuild)
    return ok(request, cw.model_copy(update={"sheet_id": sheet_id}))


@router.patch(
    "/workbooks/{id}/sheets/{sheet_id}/cells", response_model=Envelope[CellsChangedResult]
)
async def edit_cells(
    id: str,
    sheet_id: str,
    body: CellEditRequest,
    request: Request,
    ctx: Ctx,
    db: Db,
) -> Envelope[CellsChangedResult]:
    """One request = one history entry. Atomic: it all applies or none of it does."""
    st = request.app.state
    row = await history_service.lock_workbook(db, ctx.user.id, id)  # row lock held until commit
    if sheet_id not in {s.id for s in wb_service.workbook_meta(row).sheets}:
        raise DomainError("not_found")
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    result = await history_service.apply_edits(
        db, st.services, st.copies, row, entry, sheet_id, body
    )
    return ok(request, result)


def _need_find_fill(st: Any) -> None:
    if not st.services.find_fill_available:
        raise DomainError(
            "operation_conflict",
            "This engine version does not support find and fill.",
            details=[ErrorDetail(code="engine.not_implemented", message="find_fill")],
        )


@router.get("/workbooks/{id}/sheets/{sheet_id}/find", response_model=Envelope[FindResult])
async def find_in_sheet(
    id: str,
    sheet_id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    match_case: bool = False,
    whole_cell: bool = False,
    in_formulas: bool = False,
    after_row: Annotated[int | None, Query(ge=0)] = None,
    after_col: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> Envelope[FindResult]:
    """Cells whose shown text contains `q`, row-major, after the given cell (Ctrl+F)."""
    st = request.app.state
    row = await get_owned(db, WorkbookRow, ctx.user.id, id)
    if sheet_id not in {s.id for s in wb_service.workbook_meta(row).sheets}:
        raise DomainError("not_found")
    _need_find_fill(st)
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    after = (
        (after_row, after_col if after_col is not None else -1) if after_row is not None else None
    )
    found, more = await st.copies.call(
        entry,
        st.services.engine.find_cells,
        entry.handle,
        entry.to_engine(sheet_id),
        q,
        match_case=match_case,
        whole_cell=whole_cell,
        in_formulas=in_formulas,
        after=after,
        limit=limit,
    )
    return ok(request, FindResult(matches=[FindMatch(r=r, c=c) for r, c in found], truncated=more))


@router.post("/workbooks/{id}/sheets/{sheet_id}/fill", response_model=Envelope[CellsChangedResult])
async def fill_range(
    id: str,
    sheet_id: str,
    body: FillRequest,
    request: Request,
    ctx: Ctx,
    db: Db,
) -> Envelope[CellsChangedResult]:
    """Continue a range into the cells next to it (fill handle, Ctrl+D/R): one history entry."""
    st = request.app.state
    row = await history_service.lock_workbook(db, ctx.user.id, id)
    if sheet_id not in {s.id for s in wb_service.workbook_meta(row).sheets}:
        raise DomainError("not_found")
    _need_find_fill(st)
    if body.source.sheet_id != sheet_id or body.target.sheet_id != sheet_id:
        raise DomainError("validation_error", "The fill ranges must be on this sheet.")
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    s, t = body.source, body.target
    edits = await st.copies.call(
        entry,
        st.services.engine.fill_edits,
        entry.handle,
        entry.to_engine(sheet_id),
        (s.r0, s.c0, s.r1, s.c1),
        (t.r0, t.c0, t.r1, t.c1),
    )
    result = await history_service.apply_edits(
        db,
        st.services,
        st.copies,
        row,
        entry,
        sheet_id,
        CellEditRequest(base_seq=body.base_seq, edits=edits),
    )
    return ok(request, result)


def _need_calendar(st: Any) -> None:
    if not st.services.calendar_available:
        raise DomainError(
            "operation_conflict",
            "This engine version does not support calendars.",
            details=[ErrorDetail(code="engine.not_implemented", message="set_calendar")],
        )


@router.get("/workbooks/{id}/sheets/{sheet_id}/date-columns", response_model=Envelope[DateColumns])
async def get_date_columns(
    id: str, sheet_id: str, request: Request, ctx: Ctx, db: Db
) -> Envelope[DateColumns]:
    """Columns that hold dates, so the client can offer the Jalali/Gregorian/Hijri switch."""
    st = request.app.state
    _need_calendar(st)
    row = await get_owned(db, WorkbookRow, ctx.user.id, id)
    if sheet_id not in {s.id for s in wb_service.workbook_meta(row).sheets}:
        raise DomainError("not_found")
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    found = await st.copies.call(
        entry, st.services.engine.detect_date_columns, entry.handle, entry.to_engine(sheet_id)
    )
    return ok(
        request,
        DateColumns(sheet_id=sheet_id, columns=[DateColumn.model_validate(d) for d in found]),
    )


@router.put("/workbooks/{id}/calendar", response_model=Envelope[Workbook])
async def set_calendar(
    id: str, body: SetCalendarRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[Workbook]:
    """A view option, not an edit: no history entry. Dates are stored as serials either way; only
    how date functions read and write them changes, so the client reloads its cells afterwards."""
    st = request.app.state
    _need_calendar(st)
    row = await history_service.lock_workbook(db, ctx.user.id, id)
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    await st.copies.call(entry, st.services.engine.set_calendar, entry.handle, body.calendar)
    meta = dict(row.meta_json)
    meta["calendar"] = body.calendar
    row.meta_json = meta  # reassign: SQLAlchemy does not see in-place JSON mutation
    await history_service.commit_or_drop(db, st.copies, row.id)
    return ok(request, wb_service.workbook_meta(row))


@router.post("/workbooks/{id}/save", response_model=Envelope[FileRecord])
async def save_workbook(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[FileRecord]:
    """Writes the working copy as a new xlsx version (the previous one stays; history up to now is
    baked into it). The workbook reopens from the newest version."""
    rec = await exports_service.save_version(db, request.app.state, ctx.user.id, id)
    return ok(request, file_out(rec))


@router.post("/workbooks/{id}/export", status_code=202, response_model=Envelope[Job])
async def export_workbook(
    id: str, body: ExportRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[Job]:
    """Always a job: poll GET /jobs/{id}; the result is a file (GET /files/{id}/download) and the
    export report is at GET /jobs/{id}/compatibility."""
    st = request.app.state
    row = await get_owned(db, WorkbookRow, ctx.user.id, id)
    sheet_ids = {s.id for s in wb_service.workbook_meta(row).sheets}
    if body.format == "csv" and body.sheet_id not in sheet_ids:
        raise DomainError("validation_failed", "A csv export needs a valid sheet_id.")
    job_id = await st.runner.submit(
        db, ctx.user.id, "export", {"doc_id": id, "request": body.model_dump(mode="json")}
    )
    await db.commit()
    job = await db.get(JobRow, job_id)
    if job is None:
        raise DomainError("internal_error")
    return ok(request, job_out(job))
