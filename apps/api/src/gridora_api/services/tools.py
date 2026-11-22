"""Saved tools: a pipeline with named inputs, stored per user and run on a workbook range.

Running is all-or-nothing in the executor; each step then becomes its own history entry, so each
can be undone alone. Only sheet-range pipelines are supported for now (table pipelines need
table history, which comes later); a run whose result is not a plain cell patch is rolled back.
"""

from __future__ import annotations

import uuid
from typing import Any

from gridora_contracts.models import (
    CellPatchDelta,
    ErrorDetail,
    Operation,
    Pipeline,
    Range,
    SheetRangeTarget,
    Tool,
    ToolRunRequest,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import DomainError
from ..db.models import ToolRow, WorkbookRow
from ..db.repos.owned import get_owned
from . import history as history_service
from . import operations as ops_service
from . import tables as table_service
from . import workbooks as wb_service

MAX_TOOLS_PER_USER = 200
MAX_STEPS = 30


def tool_out(row: ToolRow) -> Tool:
    return Tool.model_validate(
        {
            **row.tool_json,
            "id": str(row.id),
            "owner_id": str(row.owner_id),
            "created_at": row.created_at,
        }
    )


def _stored(tool: Tool) -> dict[str, Any]:
    return tool.model_dump(mode="json", exclude={"id", "owner_id", "created_at"})


def validate_static(st: Any, tool: Tool) -> None:
    """Checks that need no data: known operations, parameters, placeholders, declared inputs."""
    if not tool.pipeline.steps or len(tool.pipeline.steps) > MAX_STEPS:
        raise DomainError(
            "validation_failed",
            details=[
                ErrorDetail(
                    code="tool.steps", path="/pipeline/steps", message=f"1 to {MAX_STEPS} steps"
                )
            ],
        )
    dummy = SheetRangeTarget(range=Range(sheet_id="-", r0=0, c0=0, r1=0, c1=0))
    try:
        errors = st.services.executor.validate_tool(tool, dummy, None)
    except Exception as exc:
        mapped = table_service.translate(exc)
        if mapped is None:
            raise
        raise mapped from None
    if errors:
        raise DomainError("validation_failed", details=ops_service.details_of(errors))


async def list_tools(db: AsyncSession, owner_id: uuid.UUID) -> list[Tool]:
    rows = (
        (
            await db.execute(
                select(ToolRow).where(ToolRow.owner_id == owner_id).order_by(ToolRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [tool_out(r) for r in rows]


async def create_tool(db: AsyncSession, st: Any, owner_id: uuid.UUID, tool: Tool) -> Tool:
    validate_static(st, tool)
    count = (
        await db.execute(
            select(func.count()).select_from(ToolRow).where(ToolRow.owner_id == owner_id)
        )
    ).scalar_one()
    if count >= MAX_TOOLS_PER_USER:
        raise DomainError(
            "operation_conflict",
            details=[ErrorDetail(code="tools.too_many", message="too many saved tools")],
        )
    row = ToolRow(owner_id=owner_id, name=tool.name, tool_json=_stored(tool))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return tool_out(row)


async def update_tool(
    db: AsyncSession, st: Any, owner_id: uuid.UUID, tool_id: str, tool: Tool
) -> Tool:
    row = await get_owned(db, ToolRow, owner_id, tool_id)
    validate_static(st, tool)
    row.name = tool.name
    row.tool_json = _stored(tool)  # reassign: JSON is not tracked in place
    await db.commit()
    await db.refresh(row)
    return tool_out(row)


async def delete_tool(db: AsyncSession, owner_id: uuid.UUID, tool_id: str) -> None:
    await db.delete(await get_owned(db, ToolRow, owner_id, tool_id))
    await db.commit()


async def run_tool(st: Any, owner_id: uuid.UUID, tool_id: str, req: ToolRunRequest) -> int:
    """Own session and transaction (a job body). Returns the seq of the last history entry."""
    async with st.sessionmaker() as db:
        trow = await get_owned(db, ToolRow, owner_id, tool_id)
        tool = tool_out(trow)
        row = await history_service.lock_workbook(db, owner_id, req.workbook_id)
        if tool.pipeline.input_kind != "sheet_range" or not isinstance(
            req.target, SheetRangeTarget
        ):
            raise DomainError(
                "operation_conflict",
                details=[
                    ErrorDetail(
                        code="tool.unsupported_input",
                        message="only sheet-range tools can run on a workbook for now",
                    )
                ],
            )
        probe = Operation(type=tool.pipeline.steps[0].type, target=req.target)
        await ops_service.verify_targets(db, owner_id, row, probe)
        history_service.check_base(req.base_seq, await history_service.head_seq(db, row.id))
        descs = [ops_service.descriptor_for(st.services, s.type) for s in tool.pipeline.steps]
        if not req.confirm_destructive:
            for d in descs:
                ops_service.check_confirmation(d, False)
        entry = await wb_service.ensure_open(
            db,
            st.services,
            st.copies,
            st.layout,
            row,
            time_limit=st.settings.import_timeout_seconds,
        )
        ctx = ops_service.exec_context(st.services, row, entry)
        ex = st.services.executor
        errors = await st.copies.call(entry, ex.validate_tool, tool, req.target, ctx)
        if errors:
            raise DomainError("validation_failed", details=ops_service.details_of(errors))
        try:
            pipeline: Pipeline = ex.bind_tool(tool, req.inputs)
            results = await st.copies.call(entry, ex.run_pipeline, pipeline, req.target, ctx)
        except DomainError:
            raise
        except Exception as exc:
            mapped = table_service.translate(exc)
            if mapped is None:
                raise
            raise mapped from None

        bad = [r for r in results if r.status != "ok" or not isinstance(r.delta, CellPatchDelta)]
        if bad or any(r.output is not None for r in results):
            st.copies.drop(str(row.id))  # rebuilt from storage + history: the run leaves no trace
            raise DomainError(
                "operation_conflict",
                details=[
                    ErrorDetail(
                        code="tool.unsupported_output",
                        message="a step did not produce a plain cell change; nothing was kept",
                    )
                ],
            )
        last = 0
        for step, desc, res in zip(tool.pipeline.steps, descs, results, strict=True):
            delta = res.delta
            if not isinstance(delta, CellPatchDelta):
                continue  # unreachable: checked above
            op = Operation(
                type=step.type,
                target=req.target,
                params=step.params,
                schema_version=step.schema_version,
            )
            h = await history_service.record_entry(db, st.copies, row, op, delta, desc.label)
            last = h.seq
            if delta.after:
                history_service.grow_dimensions(
                    row,
                    delta.sheet_id,
                    max(c.r for c in delta.after) + 1,
                    max(c.c for c in delta.after) + 1,
                )
        await history_service.commit_or_drop(db, st.copies, row.id)
        return last
