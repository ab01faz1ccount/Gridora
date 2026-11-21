"""Export and save: the working copy written through the engine into a new stored file.

export  -> a downloadable file of kind "export" (xlsx for the workbook, csv for one sheet) plus the
           export CompatibilityReport (kept on the job so nothing is lost silently).
save    -> a new xlsx version of the workbook (kind "workbook", parent = the previous version). The
           workbook then reopens from it, so history up to this point is baked in (last_saved_seq).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from gridora_contracts.models import CompatibilityReport, ExportRequest
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import DomainError
from ..db.models import StoredFile, WorkbookRow
from ..storage.atomic import move_into_place
from ..storage.layout import StorageLayout
from . import history as history_service
from . import workbooks as wb_service

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def file_name(base: str, ext: str, sheet: str | None = None) -> str:
    """A label only (never a path component): the workbook's name without its extension."""
    stem = _UNSAFE.sub("_", base.rsplit(".", 1)[0] if "." in base else base).strip() or "workbook"
    return f"{stem[:120]}{'-' + _UNSAFE.sub('_', sheet)[:60] if sheet else ''}.{ext}"


def _sha256(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


async def _write(
    db: AsyncSession,
    st: Any,
    row: WorkbookRow,
    *,
    fmt: str,
    sheet_id: str | None,
    kind: str,
    parent_id: uuid.UUID | None,
) -> tuple[StoredFile, CompatibilityReport]:
    """Export the open working copy into storage and record it. The caller commits."""
    layout: StorageLayout = st.layout
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, layout, row, time_limit=st.settings.import_timeout_seconds
    )
    tmp = layout.quarantine_path(uuid.uuid4())
    tmp.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    sheet_label: str | None = None
    try:
        if fmt == "xlsx":
            report = await st.copies.call(entry, st.services.engine.export_xlsx, entry.handle, tmp)
        else:
            meta = wb_service.workbook_meta(row)
            sheets = {s.id: s for s in meta.sheets}
            if sheet_id is None or sheet_id not in sheets:
                raise DomainError("validation_failed", "A csv export needs a valid sheet_id.")
            sheet_label = sheets[sheet_id].name
            report = await st.copies.call(
                entry, st.services.engine.export_csv, entry.handle, entry.to_engine(sheet_id), tmp
            )
        digest, size = _sha256(tmp)
        file_id = uuid.uuid4()
        key = layout.file_key(row.owner_id, kind, file_id, fmt)
        move_into_place(tmp, layout.resolve_key(key))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    rec = StoredFile(
        id=file_id,
        owner_id=row.owner_id,
        workspace_id=row.workspace_id,
        kind=kind,
        display_name=file_name(row.name, fmt, sheet_label if fmt == "csv" else None),
        size_bytes=size,
        sha256=digest,
        parent_id=parent_id,
        storage_key=key,
    )
    try:
        db.add(rec)
        await db.flush()
    except BaseException:
        layout.resolve_key(key).unlink(missing_ok=True)  # never leave an orphan
        raise
    return rec, report


async def run_export(
    st: Any, owner_id: uuid.UUID, doc_id: str, req: ExportRequest
) -> tuple[str, dict[str, Any]]:
    """Job body. Returns (file id, export report as JSON)."""
    async with st.sessionmaker() as db:
        row = await history_service.lock_workbook(db, owner_id, doc_id)  # no edit mid-export
        rec, report = await _write(
            db, st, row, fmt=req.format, sheet_id=req.sheet_id, kind="export", parent_id=None
        )
        await db.commit()
        return str(rec.id), report.model_dump(mode="json")


async def save_version(db: AsyncSession, st: Any, owner_id: uuid.UUID, doc_id: str) -> StoredFile:
    row = await history_service.lock_workbook(db, owner_id, doc_id)
    parent = row.current_file_id or row.file_id
    rec, _report = await _write(
        db, st, row, fmt="xlsx", sheet_id=None, kind="workbook", parent_id=parent
    )
    row.current_file_id = rec.id
    row.last_saved_seq = await history_service.head_seq(db, row.id)
    try:
        await db.commit()
    except BaseException:
        st.layout.resolve_key(rec.storage_key).unlink(missing_ok=True)
        raise
    return rec
