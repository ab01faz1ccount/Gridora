"""Data Tables: metadata and the current-version pointer live in Postgres, the immutable Parquet
versions in the table store (packages/dataops, reached only through the TableStore protocol).

The store raises its own typed errors; they are recognised here by their attributes (this package
never imports dataops) and mapped to the API envelope.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from gridora_contracts.models import (
    Column,
    CreateTableRequest,
    DataTable,
    ErrorDetail,
    FromRangeRequest,
    TablePreview,
    TableRows,
    TableSource,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..core.errors import DomainError
from ..db.models import DataTableRow, Document, WorkbookRow
from ..db.repos.owned import get_owned
from ..storage.layout import StorageLayout
from . import operations as ops_service
from . import workbooks as wb_service

MAX_ROWS_PER_CREATE = 10_000
MAX_PAGE = 1_000

_NOT_FOUND = {"table_not_found"}
_CONFLICT = {
    "range_has_formulas",
    "would_overwrite",
    "too_large_for_history",
    "version_conflict",
    "version_unavailable",
    "pipeline_aborted",
    "rollback_incomplete",
}
_BAD_REQUEST = {"not_implemented"}


def translate(exc: BaseException) -> DomainError | None:
    """A dataops error (attributes `code`, `message`, `errors`) as a DomainError, else None."""
    code, message = getattr(exc, "code", None), getattr(exc, "message", None)
    if not (isinstance(code, str) and isinstance(message, str) and hasattr(exc, "errors")):
        return None
    top = (
        "not_found"
        if code in _NOT_FOUND
        else "operation_conflict"
        if code in _CONFLICT
        else "bad_request"
        if code in _BAD_REQUEST
        else "internal_error"
        if code == "owner_unknown"
        else "validation_failed"
    )
    return DomainError(top, message, details=[ErrorDetail(code=code, message=message)])


async def _run(fn: Any, *args: Any, **kw: Any) -> Any:
    try:
        return await run_in_threadpool(fn, *args, **kw)
    except DomainError:
        raise
    except Exception as exc:
        mapped = translate(exc)
        if mapped is None:
            raise
        raise mapped from None


def store_for(st: Any, owner_id: uuid.UUID) -> Any:
    """The table store bound to one owner (the contract methods without a context need it)."""
    store = st.services.table_store
    return store.for_owner(str(owner_id)) if hasattr(store, "for_owner") else store


def table_out(row: DataTableRow) -> DataTable:
    return DataTable.model_validate(row.meta_json)


def _canonical(dt: DataTable, workspace_id: uuid.UUID, source: TableSource | None) -> DataTable:
    """The API's id form (hyphenated UUID, the same as the document registry) and workspace."""
    return dt.model_copy(
        update={"id": str(uuid.UUID(dt.id)), "workspace_id": str(workspace_id), "source": source}
    )


async def _register(
    db: AsyncSession, st: Any, owner_id: uuid.UUID, workspace_id: uuid.UUID, dt: DataTable
) -> DataTableRow:
    """Record a table the store just created. If the database refuses, the files are removed."""
    tid = uuid.UUID(dt.id)
    row = DataTableRow(
        id=tid,
        owner_id=owner_id,
        workspace_id=workspace_id,
        name=dt.name,
        current_version=dt.version,
        meta_json=dt.model_dump(mode="json", exclude_none=True),
    )
    try:
        db.add(Document(id=tid, owner_id=owner_id, kind="table"))
        await db.flush()
        db.add(row)
        await db.commit()
    except BaseException:
        await db.rollback()
        remove_table_files(st.layout, owner_id, [tid])
        raise
    return row


def remove_table_files(layout: StorageLayout, owner_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    for tid in ids:
        try:
            shutil.rmtree(layout.table_path(str(owner_id), str(tid), 1).parent, ignore_errors=True)
        except Exception:  # noqa: BLE001 - best effort
            pass


async def create_table(
    db: AsyncSession, st: Any, owner_id: uuid.UUID, workspace_id: uuid.UUID, req: CreateTableRequest
) -> DataTable:
    if len(req.rows) > MAX_ROWS_PER_CREATE:
        raise DomainError(
            "validation_failed",
            details=[
                ErrorDetail(
                    code="rows.too_many",
                    path="/rows",
                    message=f"at most {MAX_ROWS_PER_CREATE} rows; use a sheet range for more",
                )
            ],
        )
    ctx = _WorkspaceCtx(str(owner_id), str(workspace_id))
    store = store_for(st, owner_id)
    dt: DataTable = await _run(
        store.create_from_rows,
        ctx,
        req.name.strip() or "Table",
        [c.model_dump() for c in req.columns],
        req.rows,
    )
    dt = _canonical(dt, workspace_id, None)
    await _register(db, st, owner_id, workspace_id, dt)
    return dt


class _WorkspaceCtx:
    """The two attributes the store reads from an ExecContext when no workbook is involved."""

    def __init__(self, user_id: str, workspace_id: str) -> None:
        self.user_id, self.workspace_id = user_id, workspace_id


async def from_range(
    db: AsyncSession, st: Any, owner_id: uuid.UUID, req: FromRangeRequest
) -> DataTable | TablePreview:
    row = await get_owned(db, WorkbookRow, owner_id, req.workbook_id)
    if req.range.sheet_id not in {s["id"] for s in row.meta_json.get("sheets", [])}:
        raise DomainError("not_found")
    entry = await wb_service.ensure_open(
        db, st.services, st.copies, st.layout, row, time_limit=st.settings.import_timeout_seconds
    )
    ctx = ops_service.exec_context(st.services, row, entry)
    store = store_for(st, owner_id)
    result = await st.copies.call(
        entry,
        lambda: _guarded(
            store.sheet_range_to_table,
            ctx,
            req.range,
            req.header_row,
            req.dtype_overrides,
            req.preview,
            req.name,
        ),
    )
    if req.preview:
        return TablePreview.model_validate(result.model_dump())
    source = TableSource(workbook_id=str(row.id), range=req.range, link="snapshot")
    dt = _canonical(result, row.workspace_id, source)
    await _register(db, st, owner_id, row.workspace_id, dt)
    return dt


def _guarded(fn: Any, *args: Any) -> Any:
    """Blocking: runs inside copies.call (a worker thread holding the workbook lock)."""
    try:
        return fn(*args)
    except Exception as exc:
        mapped = translate(exc)
        if mapped is None:
            raise
        raise mapped from None


async def read_rows(
    db: AsyncSession,
    st: Any,
    owner_id: uuid.UUID,
    table_id: str,
    offset: int,
    limit: int,
    sort: str | None,
) -> TableRows:
    row = await get_owned(db, DataTableRow, owner_id, table_id)
    meta = table_out(row)
    page = await _run(
        store_for(st, owner_id).read_page,
        str(row.id),
        offset,
        min(limit, MAX_PAGE),
        sort,
        row.current_version,
    )
    return TableRows(
        table_id=str(row.id),
        version=row.current_version,
        columns=[Column.model_validate(c) for c in meta.columns],
        row_count=meta.row_count,
        offset=offset,
        rows=page,
    )


async def list_tables(
    db: AsyncSession, owner_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[DataTable]:
    rows = (
        (
            await db.execute(
                select(DataTableRow)
                .where(DataTableRow.owner_id == owner_id, DataTableRow.workspace_id == workspace_id)
                .order_by(DataTableRow.created_at)
                .limit(1000)
            )
        )
        .scalars()
        .all()
    )
    return [table_out(r) for r in rows]
