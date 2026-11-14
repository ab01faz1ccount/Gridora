from __future__ import annotations

import re
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from gridora_contracts.models import FileRecord
from gridora_contracts.models import Workspace as WorkspaceOut
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.envelope import Envelope, ok
from ...core.errors import DomainError, request_id_of
from ...db.models import StoredFile, Workspace
from ...db.repos.owned import get_owned, list_owned
from ...db.session import get_db
from ...services import audit
from ...services import files as file_service
from ...services.auth import AuthContext
from ..deps import auth, client_ip

router = APIRouter(tags=["workspaces"])
Ctx = Annotated[AuthContext, Depends(auth)]
Db = Annotated[AsyncSession, Depends(get_db)]
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class NameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not v or _CTRL.search(v):
            raise ValueError("name must be non-empty text without control characters")
        return v


class UploadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: FileRecord
    job_id: str | None = None  # import jobs arrive with PR 5


def ws_out(w: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=str(w.id), owner_id=str(w.owner_id), name=w.name, created_at=w.created_at
    )


def file_out(f: StoredFile) -> FileRecord:
    # Built field by field: storage_key is never part of the response model.
    return FileRecord(
        id=str(f.id),
        workspace_id=str(f.workspace_id),
        owner_id=str(f.owner_id),
        kind=cast(Literal["workbook", "table", "original"], f.kind),
        display_name=f.display_name,
        size_bytes=f.size_bytes,
        sha256=f.sha256,
        created_at=f.created_at,
        parent_id=str(f.parent_id) if f.parent_id else None,
    )


@router.get("/workspaces", response_model=Envelope[list[WorkspaceOut]])
async def list_workspaces(request: Request, ctx: Ctx, db: Db) -> Envelope[list[WorkspaceOut]]:
    rows = await list_owned(db, Workspace, ctx.user.id)
    return ok(request, [ws_out(w) for w in rows])


@router.post("/workspaces", status_code=201, response_model=Envelope[WorkspaceOut])
async def create_workspace(
    body: NameBody, request: Request, ctx: Ctx, db: Db
) -> Envelope[WorkspaceOut]:
    w = Workspace(owner_id=ctx.user.id, name=body.name)
    db.add(w)
    audit.record(
        db,
        action="workspace.create",
        outcome="success",
        actor_id=ctx.user.id,
        target_kind="workspace",
        target_id=str(w.id),
        ip=client_ip(request),
        request_id=request_id_of(request),
    )
    await db.commit()
    return ok(request, ws_out(w))


@router.get("/workspaces/{id}", response_model=Envelope[WorkspaceOut])
async def get_workspace(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[WorkspaceOut]:
    return ok(request, ws_out(await get_owned(db, Workspace, ctx.user.id, id)))


@router.patch("/workspaces/{id}", response_model=Envelope[WorkspaceOut])
async def rename_workspace(
    id: str, body: NameBody, request: Request, ctx: Ctx, db: Db
) -> Envelope[WorkspaceOut]:
    w = await get_owned(db, Workspace, ctx.user.id, id)
    w.name = body.name
    await db.commit()
    return ok(request, ws_out(w))


@router.delete("/workspaces/{id}", status_code=204)
async def delete_workspace(
    id: str, request: Request, ctx: Ctx, db: Db, confirm: bool = False
) -> None:
    w = await get_owned(db, Workspace, ctx.user.id, id)
    if not confirm:
        raise DomainError(
            "operation_conflict", "Deleting a workspace is destructive; resend with ?confirm=true."
        )
    files = await list_owned(
        db, StoredFile, ctx.user.id, StoredFile.workspace_id == w.id, limit=100_000
    )
    keys = [f.storage_key for f in files]
    await db.execute(
        delete(Workspace).where(Workspace.id == w.id, Workspace.owner_id == ctx.user.id)
    )
    audit.record(
        db,
        action="workspace.delete",
        outcome="success",
        actor_id=ctx.user.id,
        target_kind="workspace",
        target_id=str(w.id),
        ip=client_ip(request),
        request_id=request_id_of(request),
    )
    await db.commit()
    file_service.remove_stored(request.app.state.layout, keys)  # after commit; best effort


@router.get("/workspaces/{id}/files", response_model=Envelope[list[FileRecord]])
async def list_files(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[list[FileRecord]]:
    w = await get_owned(db, Workspace, ctx.user.id, id)
    rows = await list_owned(db, StoredFile, ctx.user.id, StoredFile.workspace_id == w.id)
    return ok(request, [file_out(f) for f in rows])


@router.post("/workspaces/{id}/files", status_code=201, response_model=Envelope[UploadResult])
async def upload_file(id: str, request: Request, ctx: Ctx, db: Db) -> Envelope[UploadResult]:
    w = await get_owned(db, Workspace, ctx.user.id, id)  # ownership BEFORE reading the body
    settings = request.app.state.settings
    cl = request.headers.get("content-length")
    stored = await file_service.receive(
        request.stream(),
        request.headers.get("content-type", ""),
        int(cl) if cl and cl.isdigit() else None,
        request.app.state.layout,
        settings.max_upload_bytes,
    )
    rec: StoredFile | None = None
    try:
        rec = await file_service.finalize_upload(
            db, request.app.state.layout, owner_id=ctx.user.id, workspace_id=w.id, stored=stored
        )
        audit.record(
            db,
            action="file.upload",
            outcome="success",
            actor_id=ctx.user.id,
            target_kind="file",
            target_id=str(rec.id),
            ip=client_ip(request),
            request_id=request_id_of(request),
        )
        await db.commit()
    except BaseException:
        if rec is not None:  # the file was already moved into place; do not leave an orphan
            file_service.remove_stored(request.app.state.layout, [rec.storage_key])
        stored.quarantine.unlink(missing_ok=True)
        raise
    return ok(request, UploadResult(file=file_out(rec)))


@router.get("/files/{id}/download")
async def download_file(id: str, request: Request, ctx: Ctx, db: Db) -> FileResponse:
    f = await get_owned(db, StoredFile, ctx.user.id, id)
    path = request.app.state.layout.resolve_key(f.storage_key)
    if not path.is_file():
        raise DomainError("not_found")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f.display_name,
        content_disposition_type="attachment",
    )
