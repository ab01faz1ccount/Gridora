"""Charts: a definition (contract ChartSpec) kept per document; the data is computed on demand by
the dataops executor, from the workbook's sheet range or from the table's current version."""

from __future__ import annotations

import uuid
from typing import Any

from gridora_contracts.models import (
    ChartData,
    ChartSpec,
    DataTableTarget,
    ErrorDetail,
    SheetRangeTarget,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..core.errors import DomainError
from ..db.models import ChartRow, DataTableRow, Document, WorkbookRow
from ..db.repos.owned import get_owned
from . import operations as ops_service
from . import tables as table_service
from . import workbooks as wb_service

MAX_CHARTS_PER_DOCUMENT = 50


class _TableOnlyContext:
    """What the executor reads from an ExecContext when the source is a Data Table."""

    def __init__(self, user_id: str, workspace_id: str, store: Any) -> None:
        self.user_id, self.workspace_id, self._store = user_id, workspace_id, store

    def table_store(self) -> Any:  # a method in the ExecContext protocol
        return self._store


def _bad_source(message: str) -> DomainError:
    return DomainError(
        "validation_failed",
        details=[ErrorDetail(code="chart.bad_source", path="/source", message=message)],
    )


async def _checked(
    db: AsyncSession, owner_id: uuid.UUID, doc_id: str, spec: ChartSpec
) -> tuple[Document, ChartSpec]:
    """The document is the owner's; the source lives in that document (never another one's)."""
    doc = await get_owned(db, Document, owner_id, doc_id)
    src = spec.source
    if doc.kind == "workbook":
        wb = await get_owned(db, WorkbookRow, owner_id, doc_id)
        if not isinstance(src, SheetRangeTarget):
            raise _bad_source("a workbook chart needs a sheet range")
        if src.range.sheet_id not in {s["id"] for s in wb.meta_json.get("sheets", [])}:
            raise _bad_source("the sheet is not in this workbook")
    else:
        t = await get_owned(db, DataTableRow, owner_id, doc_id)
        if not isinstance(src, DataTableTarget) or src.table_id != str(t.id):
            raise _bad_source("a table chart needs that table as its source")
    return doc, spec.model_copy(update={"document_id": str(doc.id)})


def spec_out(row: ChartRow) -> ChartSpec:
    return ChartSpec.model_validate({**row.spec_json, "id": str(row.id)})


async def list_charts(db: AsyncSession, owner_id: uuid.UUID, doc_id: str) -> list[ChartSpec]:
    doc = await get_owned(db, Document, owner_id, doc_id)
    rows = (
        (
            await db.execute(
                select(ChartRow)
                .where(ChartRow.owner_id == owner_id, ChartRow.document_id == doc.id)
                .order_by(ChartRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [spec_out(r) for r in rows]


async def create_chart(
    db: AsyncSession, owner_id: uuid.UUID, doc_id: str, spec: ChartSpec
) -> ChartSpec:
    doc, spec = await _checked(db, owner_id, doc_id, spec)
    count = (
        await db.execute(
            select(func.count()).select_from(ChartRow).where(ChartRow.document_id == doc.id)
        )
    ).scalar_one()
    if count >= MAX_CHARTS_PER_DOCUMENT:
        raise DomainError(
            "operation_conflict",
            details=[ErrorDetail(code="charts.too_many", message="too many charts")],
        )
    row = ChartRow(
        owner_id=owner_id,
        document_id=doc.id,
        spec_json=spec.model_dump(mode="json", exclude={"id"}),
    )
    db.add(row)
    await db.commit()
    return spec_out(row)


async def update_chart(
    db: AsyncSession, owner_id: uuid.UUID, chart_id: str, spec: ChartSpec
) -> ChartSpec:
    row = await get_owned(db, ChartRow, owner_id, chart_id)
    _doc, spec = await _checked(db, owner_id, str(row.document_id), spec)
    row.spec_json = spec.model_dump(mode="json", exclude={"id"})  # reassign: JSON is not tracked
    await db.commit()
    return spec_out(row)


async def delete_chart(db: AsyncSession, owner_id: uuid.UUID, chart_id: str) -> None:
    row = await get_owned(db, ChartRow, owner_id, chart_id)
    await db.delete(row)
    await db.commit()


async def chart_data(db: AsyncSession, st: Any, owner_id: uuid.UUID, chart_id: str) -> ChartData:
    row = await get_owned(db, ChartRow, owner_id, chart_id)
    spec = spec_out(row)
    doc = await get_owned(db, Document, owner_id, str(row.document_id))
    try:
        if doc.kind == "workbook":
            wb = await get_owned(db, WorkbookRow, owner_id, str(doc.id))
            entry = await wb_service.ensure_open(
                db, st.services, st.copies, st.layout, wb,
                time_limit=st.settings.import_timeout_seconds,
            )
            ctx = ops_service.exec_context(st.services, wb, entry)
            result: ChartData = await st.copies.call(
                entry, st.services.executor.chart_data, spec, ctx
            )
            return result
        t = await get_owned(db, DataTableRow, owner_id, str(doc.id))
        src = spec.source
        if not isinstance(src, DataTableTarget):
            raise _bad_source("a table chart needs that table as its source")
        spec = spec.model_copy(
            update={"source": src.model_copy(update={"version": t.current_version})}
        )
        tctx = _TableOnlyContext(str(owner_id), str(t.workspace_id), st.services.table_store)
        result = await run_in_threadpool(st.services.executor.chart_data, spec, tctx)
        return result
    except DomainError:
        raise
    except Exception as exc:
        mapped = table_service.translate(exc)
        if mapped is None:
            raise
        raise mapped from None
