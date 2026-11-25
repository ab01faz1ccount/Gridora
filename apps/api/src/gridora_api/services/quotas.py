"""What one account may keep on this server (admins are exempt). Checked before the work is done."""

from __future__ import annotations

import uuid

from gridora_contracts.models import ErrorDetail
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..core.errors import DomainError
from ..db.models import StoredFile, User, Workspace


def _over(code: str, message: str) -> DomainError:
    return DomainError(
        "operation_conflict", message, details=[ErrorDetail(code=code, message=code)]
    )


async def check_workspace_slot(db: AsyncSession, settings: Settings, user: User) -> None:
    if user.role == "admin":
        return
    n = (
        await db.execute(
            select(func.count()).select_from(Workspace).where(Workspace.owner_id == user.id)
        )
    ).scalar_one()
    if n >= settings.max_workspaces_per_user:
        raise _over("quota.workspaces", "You have reached the number of workspaces allowed.")


async def storage_used(db: AsyncSession, owner_id: uuid.UUID) -> int:
    total = (
        await db.execute(
            select(func.coalesce(func.sum(StoredFile.size_bytes), 0)).where(
                StoredFile.owner_id == owner_id
            )
        )
    ).scalar_one()
    return int(total)


async def check_storage(db: AsyncSession, settings: Settings, user: User, incoming: int) -> None:
    if user.role == "admin":
        return
    if await storage_used(db, user.id) + incoming > settings.user_storage_bytes:
        raise _over("quota.storage", "Your storage space is full; delete files to upload more.")
