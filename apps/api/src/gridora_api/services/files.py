"""File records: placing validated uploads into storage."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import StoredFile
from ..storage.atomic import move_into_place
from ..storage.layout import StorageLayout
from .uploads import StoredUpload, receive_upload

log = logging.getLogger("gridora.files")


async def receive(
    stream: AsyncIterator[bytes],
    content_type: str,
    content_length: int | None,
    layout: StorageLayout,
    max_bytes: int,
) -> StoredUpload:
    return await receive_upload(stream, content_type, content_length, layout, max_bytes)


async def finalize_upload(
    db: AsyncSession,
    layout: StorageLayout,
    *,
    owner_id: uuid.UUID,
    workspace_id: uuid.UUID,
    stored: StoredUpload,
) -> StoredFile:
    file_id = uuid.uuid4()
    key = layout.file_key(owner_id, "original", file_id, stored.ext)
    dst = layout.resolve_key(key)
    move_into_place(stored.quarantine, dst)
    rec = StoredFile(
        id=file_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        kind="original",
        display_name=stored.display_name,
        size_bytes=stored.size,
        sha256=stored.sha256,
        storage_key=key,
    )
    try:
        db.add(rec)
        await db.flush()
        await db.refresh(rec)
    except BaseException:
        dst.unlink(missing_ok=True)  # moved but not recorded: remove, never leave an orphan
        raise
    return rec


def remove_stored(layout: StorageLayout, keys: list[str]) -> None:
    for key in keys:
        try:
            layout.resolve_key(key).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - best effort; logged without the path
            log.warning("could not remove a stored file")
