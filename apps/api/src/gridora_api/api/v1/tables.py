"""Data Tables (contract 0.6.2): list/create/get, paged rows, and creation from a sheet range."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from gridora_contracts.models import (
    CellsChangedResult,
    CreateTableRequest,
    DataTable,
    ErrorDetail,
    ExportRequest,
    FromRangeRequest,
    HistoryEntry,
    Job,
    Operation,
    OperationRequest,
    PreviewResult,
    TableChangedResult,
    TablePreview,
    TableRows,
    ToSheetRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError, request_id_of
from ...db.models import DataTableRow, JobRow, Workspace
from ...db.repos.owned import get_owned
from ...db.session import get_db
from ...services import operations as ops_service
from ...services import table_history as table_history
from ...services import tables as table_service
from ...services.auth import AuthContext
from ..deps import auth
from .jobs import job_out

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


@router.post("/tables/{id}/to-sheet", response_model=Envelope[CellsChangedResult])
async def table_to_sheet(
    id: str, body: ToSheetRequest, request: Request, ctx: Ctx
) -> Envelope[CellsChangedResult]:
    """Writes the table (header + rows) into a sheet; refuses to overwrite data. Undoable."""
    res = await table_service.to_sheet(request.app.state, ctx.user.id, id, body)
    return ok(request, res)


@router.post("/tables/{id}/operations/preview", response_model=Envelope[PreviewResult])
async def preview_table_operation(
    id: str, body: Operation, request: Request, ctx: Ctx, db: Db
) -> Envelope[PreviewResult]:
    res = await table_history.preview(db, request.app.state, ctx.user.id, id, body)
    return ok(request, res)


@router.post("/tables/{id}/operations", status_code=202, response_model=Envelope[Job])
async def apply_table_operation(
    id: str, body: OperationRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[Job]:
    """Always a job (poll GET /jobs/{id}; its result is the history seq). The result is a new
    version of the same table; GET /tables/{id} shows it. Operations that would create another
    table are refused for now (`operation.unsupported_output`)."""
    st = request.app.state
    await get_owned(db, DataTableRow, ctx.user.id, id)  # 404 for foreign ids
    desc = ops_service.descriptor_for(st.services, body.operation.type)
    ops_service.check_confirmation(desc, body.confirm_destructive)
    job_id = await st.runner.submit(
        db,
        ctx.user.id,
        "operation",
        {
            "table_id": id,
            "doc_id": id,
            "request": body.model_dump(mode="json"),
            "request_id": request_id_of(request),
        },
    )
    await db.commit()
    job = await db.get(JobRow, job_id)
    if job is None:
        raise DomainError("internal_error")
    return ok(request, job_out(job))


@router.post("/tables/{id}/undo", response_model=Envelope[TableChangedResult])
async def undo_table(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    base_seq: Annotated[int | None, Query(ge=0)] = None,
) -> Envelope[TableChangedResult]:
    res = await table_history.step(
        db, request.app.state, ctx.user.id, id, undo=True, base_seq=base_seq
    )
    return ok(request, res)


@router.post("/tables/{id}/redo", response_model=Envelope[TableChangedResult])
async def redo_table(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    base_seq: Annotated[int | None, Query(ge=0)] = None,
) -> Envelope[TableChangedResult]:
    res = await table_history.step(
        db, request.app.state, ctx.user.id, id, undo=False, base_seq=base_seq
    )
    return ok(request, res)


@router.get("/tables/{id}/history", response_model=Envelope[list[HistoryEntry]])
async def table_history_entries(
    id: str,
    request: Request,
    ctx: Ctx,
    db: Db,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Envelope[list[HistoryEntry]]:
    if cursor is not None and not cursor.isdigit():
        raise DomainError("validation_failed")
    cur = int(cursor) if cursor is not None else None
    entries, nxt = await table_history.entries(db, ctx.user.id, id, cur, limit)
    return ok(request, entries, next_cursor=nxt)


@router.post("/tables/{id}/export", status_code=202, response_model=Envelope[Job])
async def export_table(
    id: str, body: ExportRequest, request: Request, ctx: Ctx, db: Db
) -> Envelope[Job]:
    """A job like a workbook export (result_ref = the file; report at /jobs/{id}/compatibility).
    csv only; for xlsx use to-sheet, then export the workbook."""
    await get_owned(db, DataTableRow, ctx.user.id, id)
    if body.format != "csv":
        raise DomainError(
            "validation_failed",
            details=[
                ErrorDetail(
                    code="export.unsupported_format",
                    path="/format",
                    message="a table can be exported as csv",
                )
            ],
        )
    job_id = await request.app.state.runner.submit(
        db, ctx.user.id, "export", {"table_id": id, "request": body.model_dump(mode="json")}
    )
    await db.commit()
    job = await db.get(JobRow, job_id)
    if job is None:
        raise DomainError("internal_error")
    return ok(request, job_out(job))
