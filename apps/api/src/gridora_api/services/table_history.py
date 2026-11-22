"""Operations on a Data Table, with version history and undo/redo.

Every table version is an immutable Parquet file. An operation writes version N+1 and the history
entry records TableVersionDelta(table, N, N+1); undo and redo only move the current-version pointer
that Postgres owns (a swap, no data is rewritten). Only in-place operations are supported: one that
creates another table (a pivot) is refused and what it wrote is removed.
"""

from __future__ import annotations

import uuid
from typing import Any

from gridora_contracts.models import (
    DataTable,
    DataTableTarget,
    ErrorDetail,
    HistoryEntry,
    Operation,
    OperationRequest,
    PreviewResult,
    TableChangedResult,
    TableVersionDelta,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..core.errors import DomainError
from ..db.models import DataTableRow, HistoryRow
from ..db.repos.owned import get_owned, parse_id
from . import charts as chart_service
from . import history as history_service
from . import operations as ops_service
from . import tables as table_service


async def lock_table(db: AsyncSession, owner_id: uuid.UUID, raw_id: str) -> DataTableRow:
    row = (
        await db.execute(
            select(DataTableRow)
            .where(DataTableRow.id == parse_id(raw_id), DataTableRow.owner_id == owner_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise DomainError("not_found")
    return row


def _mismatch(message: str) -> DomainError:
    return DomainError(
        "validation_failed",
        details=[ErrorDetail(code="target.mismatch", path="/target", message=message)],
    )


async def _pinned(
    db: AsyncSession, owner_id: uuid.UUID, row: DataTableRow, op: Operation
) -> Operation:
    """The primary target must be this table; its version is pinned to the current pointer."""
    t = op.target
    if not isinstance(t, DataTableTarget) or t.table_id != str(row.id):
        raise _mismatch("a table operation must target that table")
    for extra in op.extra_targets:
        await ops_service.verify_one(db, owner_id, extra)
    return op.model_copy(update={"target": t.model_copy(update={"version": row.current_version})})


def _ctx(st: Any, owner_id: uuid.UUID, row: DataTableRow) -> chart_service.TableOnlyContext:
    return chart_service.TableOnlyContext(
        str(owner_id), str(row.workspace_id), st.services.table_store
    )


async def _call(fn: Any, *args: Any) -> Any:
    try:
        return await run_in_threadpool(fn, *args)
    except DomainError:
        raise
    except Exception as exc:
        mapped = table_service.translate(exc)
        if mapped is None:
            raise
        raise mapped from None


async def preview(
    db: AsyncSession, st: Any, owner_id: uuid.UUID, table_id: str, op: Operation
) -> PreviewResult:
    row = await get_owned(db, DataTableRow, owner_id, table_id)
    op = await _pinned(db, owner_id, row, op)
    ctx = _ctx(st, owner_id, row)
    ex = st.services.executor
    errors = await _call(ex.validate, op, ctx)
    if errors:
        raise DomainError("validation_failed", details=ops_service.details_of(errors))
    result: PreviewResult = await _call(ex.preview, op, ctx, ops_service.PREVIEW_LIMIT)
    return result


def _meta_at(row: DataTableRow, dt: DataTable) -> dict[str, Any]:
    """Columns and row count of version `dt`; name, workspace and source stay as they were."""
    return {
        **row.meta_json,
        "version": dt.version,
        "row_count": dt.row_count,
        "columns": [c.model_dump(mode="json", exclude_none=True) for c in dt.columns],
    }


async def run_operation(st: Any, owner_id: uuid.UUID, table_id: str, req: OperationRequest) -> int:
    """Own session and transaction (a job body). Returns the history seq it created."""
    async with st.sessionmaker() as db:
        row = await lock_table(db, owner_id, table_id)
        op = await _pinned(db, owner_id, row, req.operation)
        desc = ops_service.descriptor_for(st.services, op.type)
        ops_service.check_confirmation(desc, req.confirm_destructive)
        history_service.check_base(req.base_seq, await history_service.head_seq(db, row.id))
        ctx = _ctx(st, owner_id, row)
        ex = st.services.executor
        errors = await _call(ex.validate, op, ctx)
        if errors:
            raise DomainError("validation_failed", details=ops_service.details_of(errors))
        result = await _call(ex.apply, op, ctx)
        store = table_service.store_for(st, owner_id)
        delta = result.delta
        in_place = (
            result.status == "ok"
            and isinstance(delta, TableVersionDelta)
            and uuid.UUID(delta.table_id) == row.id
            and delta.from_version == row.current_version
            and result.output is None
        )
        if not in_place or not isinstance(delta, TableVersionDelta):
            _discard(store, owner_id, row, result)
            raise DomainError(
                "operation_conflict",
                details=[
                    ErrorDetail(
                        code="operation.unsupported_output"
                        if result.status == "ok"
                        else "operation.no_change",
                        message="the operation did not produce a new version of this table",
                    )
                ]
                + ops_service.details_of(list(result.errors)),
            )
        try:
            dt: DataTable = await _call(store.restore_version, str(row.id), delta.to_version)
            stale = await _drop_redo_tail(db, row)
            row.seq_counter += 1
            h = HistoryRow(
                document_id=row.id,
                owner_id=owner_id,
                seq=row.seq_counter,
                operation_json=op.model_dump(mode="json"),
                delta_json=delta.model_dump(mode="json"),
                label=desc.label,
                undone=False,
            )
            db.add(h)
            row.current_version = delta.to_version
            row.meta_json = _meta_at(row, dt)
            await db.commit()
        except BaseException:
            await db.rollback()
            store.discard_version(str(owner_id), str(row.id), delta.to_version)
            raise
        for v in stale:  # versions only a discarded redo tail referred to
            _quiet(store.discard_version, str(owner_id), str(row.id), v)
        return h.seq


def _discard(store: Any, owner_id: uuid.UUID, row: DataTableRow, result: Any) -> None:
    """Remove whatever a refused operation wrote."""
    d = result.delta
    if isinstance(d, TableVersionDelta):
        if uuid.UUID(d.table_id) == row.id:
            if d.to_version != row.current_version:
                _quiet(store.discard_version, str(owner_id), str(row.id), d.to_version)
        elif d.from_version == 0:
            _quiet(store.discard_table, str(owner_id), d.table_id)


def _quiet(fn: Any, *args: Any) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001, S110 - cleanup is best effort
        pass


async def _drop_redo_tail(db: AsyncSession, row: DataTableRow) -> list[int]:
    """A new entry discards what was undone; returns the versions only those entries produced."""
    tail = list(
        (
            await db.execute(
                select(HistoryRow.delta_json).where(
                    HistoryRow.document_id == row.id, HistoryRow.undone.is_(True)
                )
            )
        ).scalars()
    )
    versions = [int(d["to_version"]) for d in tail if d.get("kind") == "table_version"]
    await db.execute(
        delete(HistoryRow).where(HistoryRow.document_id == row.id, HistoryRow.undone.is_(True))
    )
    return versions


async def step(
    db: AsyncSession,
    st: Any,
    owner_id: uuid.UUID,
    table_id: str,
    *,
    undo: bool,
    base_seq: int | None,
) -> TableChangedResult:
    row = await lock_table(db, owner_id, table_id)
    history_service.check_base(base_seq, await history_service.head_seq(db, row.id))
    stmt = select(HistoryRow).where(
        HistoryRow.document_id == row.id, HistoryRow.undone.is_(not undo)
    )
    stmt = stmt.order_by(HistoryRow.seq.desc() if undo else HistoryRow.seq).limit(1)
    h = (await db.execute(stmt)).scalar_one_or_none()
    if h is None:
        code = "history.nothing_to_undo" if undo else "history.nothing_to_redo"
        raise DomainError("operation_conflict", details=[ErrorDetail(code=code, message=code)])
    delta = TableVersionDelta.model_validate(h.delta_json)
    target = delta.from_version if undo else delta.to_version
    store = table_service.store_for(st, owner_id)
    dt: DataTable = await _call(store.restore_version, str(row.id), target)  # pointer swap
    row.current_version = target
    row.meta_json = _meta_at(row, dt)
    h.undone = undo
    await db.commit()
    await db.refresh(h)
    return TableChangedResult(
        history_entry=history_service.entry_out(h), table=table_service.table_out(row)
    )


async def entries(
    db: AsyncSession, owner_id: uuid.UUID, table_id: str, cursor: int | None, limit: int
) -> tuple[list[HistoryEntry], str | None]:
    row = await get_owned(db, DataTableRow, owner_id, table_id)
    return await history_service.list_entries(db, row.id, cursor, limit)
