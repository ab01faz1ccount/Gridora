"""Opening workbooks: import a stored file into a working copy and record its metadata."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gridora_contracts.models import Workbook
from gridora_contracts.protocols import WorkbookEngine, WorkbookHandle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..composition.wiring import Services
from ..core.errors import DomainError
from ..db.models import Document, StoredFile, WorkbookRow
from ..db.repos.owned import get_owned
from ..storage.layout import StorageLayout
from .working_copies import Entry, WorkingCopies


@dataclass
class CsvOpts:
    delimiter: str | None = None
    encoding: str | None = None
    has_header: bool = True
    infer_types: bool = True


def _ext(f: StoredFile) -> str:
    return f.storage_key.rsplit(".", 1)[-1].lower()


def import_blocking(
    engine: WorkbookEngine, path: Path, ext: str, file_id: str
) -> tuple[WorkbookHandle, Workbook]:
    """Parse a stored file. Blocking: call from a worker thread."""
    if ext in ("xlsx", "xlsm"):
        handle, wb, report = engine.import_xlsx(path, file_id=file_id)
        return handle, wb.model_copy(update={"compat": report})
    if ext == "csv":
        handle, wb = engine.import_csv(path, CsvOpts(), file_id=file_id)
        return handle, wb
    raise DomainError("unsupported_media_type", "This file type cannot be opened.")


async def _import_with_timeout(
    services: Services, layout: StorageLayout, f: StoredFile, time_limit: float
) -> tuple[WorkbookHandle, Workbook]:
    path = layout.resolve_key(f.storage_key)
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, import_blocking, services.engine, path, _ext(f), str(f.id))
    try:
        return await asyncio.wait_for(fut, time_limit)
    except TimeoutError:
        # The thread cannot be killed (ADR-011: no process isolation in v1); we stop waiting.
        raise DomainError("import_failed", "Importing the file took too long.") from None


def _public(row: WorkbookRow, wb: Workbook) -> Workbook:
    """The API owns identity: Workbook.id is the document id, file_id the stored original, and
    the name is the user's display name (the engine only ever sees a UUID file name)."""
    return wb.model_copy(update={"id": str(row.id), "file_id": str(row.file_id), "name": row.name})


async def workbook_for_file(
    db: AsyncSession, owner_id: uuid.UUID, file_id: uuid.UUID
) -> WorkbookRow | None:
    return (
        await db.execute(
            select(WorkbookRow).where(
                WorkbookRow.file_id == file_id, WorkbookRow.owner_id == owner_id
            )
        )
    ).scalar_one_or_none()


async def import_file(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    layout: StorageLayout,
    *,
    owner_id: uuid.UUID,
    file: StoredFile,
    time_limit: float,
) -> WorkbookRow:
    """Import `file` (or reuse its workbook) and leave a working copy open. Idempotent per file."""
    existing = await workbook_for_file(db, owner_id, file.id)
    if existing is not None:
        await ensure_open(db, services, copies, layout, existing, time_limit=time_limit)
        return existing
    handle, wb = await _import_with_timeout(services, layout, file, time_limit)
    doc_id = uuid.uuid4()
    row = WorkbookRow(
        id=doc_id,
        owner_id=owner_id,
        workspace_id=file.workspace_id,
        file_id=file.id,
        name=file.display_name,
        last_saved_seq=0,
        meta_json={},
    )
    pub = _public(row, wb)
    row.meta_json = pub.model_dump(mode="json")
    try:
        db.add(Document(id=doc_id, owner_id=owner_id, kind="workbook"))
        await db.flush()
        db.add(row)
        await db.commit()
    except BaseException:
        services.engine.close(handle)
        raise
    copies.put(str(doc_id), handle, wb)
    return row


async def ensure_open(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    layout: StorageLayout,
    row: WorkbookRow,
    *,
    time_limit: float,
) -> Entry:
    """Working copy for a stored workbook; rebuilt from its file after a restart or eviction.
    (History replay is added with the history service in PR 10; no edits exist before that.)"""
    entry = copies.get(str(row.id))
    if entry is not None:
        return entry
    src_id = row.current_file_id or row.file_id
    f = await get_owned(db, StoredFile, row.owner_id, str(src_id))
    path = layout.resolve_key(f.storage_key)
    ext, orig_id = _ext(f), str(row.file_id)  # stable sheet ids need the ORIGINAL file id

    def loader() -> tuple[WorkbookHandle, Workbook]:
        return import_blocking(services.engine, path, ext, orig_id)

    try:
        return await asyncio.wait_for(copies.load(str(row.id), loader), time_limit)
    except TimeoutError:
        raise DomainError("import_failed", "Opening the workbook took too long.") from None


def workbook_meta(row: WorkbookRow) -> Workbook:
    return Workbook.model_validate(row.meta_json)


def meta_dict(row: WorkbookRow) -> dict[str, Any]:
    return dict(row.meta_json)
