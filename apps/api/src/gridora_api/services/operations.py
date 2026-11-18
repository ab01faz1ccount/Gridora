"""Applying operations to a workbook: validation, ownership of every target, history, undo.

Heavy work never holds an HTTP request open: the apply route queues an `operation` job and waits a
short time for it (see api/v1/operations.py). The job runs `run_operation`, which takes the same
row lock as a cell edit, so an operation and an edit can never interleave.
"""

from __future__ import annotations

import uuid
from typing import Any

from gridora_contracts.models import (
    CellPatchDelta,
    CellsChangedResult,
    ErrorDetail,
    Operation,
    OperationDescriptor,
    OperationRequest,
    PreviewResult,
    SheetRangeTarget,
    Target,
    ValidationError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..composition.exec_context import EngineExecContext
from ..composition.wiring import Services
from ..core.errors import DomainError
from ..db.models import Document, WorkbookRow
from ..db.repos.owned import get_owned
from . import history as history_service
from . import workbooks as wb_service
from .working_copies import Entry

PREVIEW_LIMIT = 100


def _details(errors: list[ValidationError]) -> list[ErrorDetail]:
    return [ErrorDetail(code=e.code, path=e.path, message=e.message, hint=e.hint) for e in errors]


def descriptor_for(services: Services, op_type: str) -> OperationDescriptor:
    for d in services.executor.describe_all():
        if d.type == op_type:
            return d
    raise DomainError(
        "validation_failed",
        details=[ErrorDetail(code="operation.unknown", path="/type", message=op_type[:60])],
    )


async def verify_targets(
    db: AsyncSession, owner_id: uuid.UUID, doc: WorkbookRow, op: Operation
) -> None:
    """EVERY target (primary and extra) must belong to the user. Modules never look ids up."""
    primary = op.target
    if not isinstance(primary, SheetRangeTarget):
        raise DomainError(
            "validation_failed",
            details=[
                ErrorDetail(
                    code="target.mismatch", path="/target", message="a workbook needs a sheet range"
                )
            ],
        )
    if primary.range.sheet_id not in {s["id"] for s in doc.meta_json.get("sheets", [])}:
        raise DomainError("not_found")
    for t in op.extra_targets:
        await _verify_one(db, owner_id, t)


async def _verify_one(db: AsyncSession, owner_id: uuid.UUID, t: Target) -> None:
    if isinstance(t, SheetRangeTarget):
        rows = (
            await db.execute(select(WorkbookRow.meta_json).where(WorkbookRow.owner_id == owner_id))
        ).scalars()
        if any(t.range.sheet_id == s["id"] for meta in rows for s in meta.get("sheets", [])):
            return
        raise DomainError("not_found")
    table_id = getattr(t, "table_id", None)
    if isinstance(table_id, str):
        doc = (
            await db.execute(
                select(Document).where(
                    Document.id == _uuid_or_404(table_id),
                    Document.owner_id == owner_id,
                    Document.kind == "table",
                )
            )
        ).scalar_one_or_none()
        if doc is not None:
            return
    raise DomainError("not_found")


def _uuid_or_404(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise DomainError("not_found") from None


def check_confirmation(desc: OperationDescriptor, confirmed: bool) -> None:
    if desc.destructive and not confirmed:
        raise DomainError(
            "operation_conflict",
            "This operation changes your data in place. Confirm to continue.",
            details=[
                ErrorDetail(
                    code="operation.confirm_required",
                    path="/confirm_destructive",
                    message="resend with confirm_destructive=true",
                )
            ],
        )


def _ctx(services: Services, row: WorkbookRow, entry: Entry) -> EngineExecContext:
    return EngineExecContext(
        services.engine,
        entry.handle,
        user_id=str(row.owner_id),
        workspace_id=str(row.workspace_id),
        store=services.table_store,
        sheet_map=entry.sheet_map,
    )


async def preview(
    db: AsyncSession, st: Any, owner_id: uuid.UUID, doc_id: str, op: Operation
) -> PreviewResult:
    row = await get_owned(db, WorkbookRow, owner_id, doc_id)
    desc = descriptor_for(st.services, op.type)
    if not desc.supports_preview:
        raise DomainError(
            "operation_conflict",
            details=[ErrorDetail(code="operation.no_preview", message=desc.type)],
        )
    await verify_targets(db, owner_id, row, op)
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    ctx = _ctx(st.services, row, entry)
    errors = await st.copies.call(entry, st.services.executor.validate, op, ctx)
    if errors:
        raise DomainError("validation_failed", details=_details(errors))
    result: PreviewResult = await st.copies.call(
        entry, st.services.executor.preview, op, ctx, PREVIEW_LIMIT
    )
    return result


async def run_operation(
    st: Any, owner_id: uuid.UUID, doc_id: str, req: OperationRequest
) -> CellsChangedResult:
    """Own session and transaction (called from the job runner). Atomic: all or nothing."""
    op = req.operation
    async with st.sessionmaker() as db:
        row = await history_service.lock_workbook(db, owner_id, doc_id)
        desc = descriptor_for(st.services, op.type)
        check_confirmation(desc, req.confirm_destructive)
        await verify_targets(db, owner_id, row, op)
        head = await history_service.head_seq(db, row.id)
        history_service.check_base(req.base_seq, head)
        entry = await wb_service.ensure_open(
            db,
            st.services,
            st.copies,
            st.layout,
            row,
            time_limit=st.settings.import_timeout_seconds,
        )
        ctx = _ctx(st.services, row, entry)
        errors = await st.copies.call(entry, st.services.executor.validate, op, ctx)
        if errors:
            raise DomainError("validation_failed", details=_details(errors))
        result = await st.copies.call(entry, st.services.executor.apply, op, ctx)
        if result.status != "ok" or result.delta is None:
            raise DomainError(
                "operation_conflict",
                details=[
                    ErrorDetail(code="operation.no_change", message="the operation changed nothing")
                ]
                + _details(list(result.errors)),
            )
        delta = result.delta
        h = await history_service.record_entry(db, st.copies, row, op, delta, desc.label)
        if isinstance(delta, CellPatchDelta) and delta.after:
            history_service.grow_dimensions(
                row,
                delta.sheet_id,
                max(c.r for c in delta.after) + 1,
                max(c.c for c in delta.after) + 1,
            )
        await history_service.commit_or_drop(db, st.copies, row.id)
        sheet = (
            delta.sheet_id if isinstance(delta, CellPatchDelta) else next(iter(entry.sheet_map), "")
        )
        return CellsChangedResult(
            history_entry=history_service.entry_out(h),
            sheet_id=sheet,
            cells=list(delta.after) if isinstance(delta, CellPatchDelta) else [],
        )
