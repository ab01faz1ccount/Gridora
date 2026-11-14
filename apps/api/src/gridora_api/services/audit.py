"""Audit log (SECURITY_MODEL): logins, logout, uploads, deletes, exports. No secrets, ever."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditLog


def record(
    db: AsyncSession,
    *,
    action: str,
    outcome: str,
    actor_id: uuid.UUID | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            target_kind=target_kind,
            target_id=target_id,
            ip=ip,
            request_id=request_id,
        )
    )
