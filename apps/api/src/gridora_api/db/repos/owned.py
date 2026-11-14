"""Owner-scoped data access. There is deliberately NO function here that fetches by id alone.

A missing row and another user's row are indistinguishable: both raise not_found (404).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.errors import DomainError
from ..models import JobRow, StoredFile, WorkbookRow, Workspace

M = TypeVar("M", Workspace, StoredFile, WorkbookRow, JobRow)


def parse_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise DomainError("not_found") from None  # a malformed id is just "not found"


async def get_owned(db: AsyncSession, model: type[M], owner_id: uuid.UUID, raw_id: str) -> M:
    row = (
        await db.execute(
            select(model).where(model.id == parse_id(raw_id), model.owner_id == owner_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise DomainError("not_found")
    return row


async def list_owned(
    db: AsyncSession, model: type[M], owner_id: uuid.UUID, *filters: Any, limit: int = 1000
) -> Sequence[M]:
    stmt = (
        select(model)
        .where(model.owner_id == owner_id, *filters)
        .order_by(model.created_at, model.id)
        .limit(limit)
    )
    return (await db.execute(stmt)).scalars().all()
