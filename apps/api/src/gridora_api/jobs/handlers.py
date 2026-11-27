"""Job handlers. They get the app state through closures built in main.py (no globals)."""

from __future__ import annotations

from typing import Any

from gridora_contracts.models import (
    ExportRequest,
    OperationRequest,
    TableToolRunRequest,
    ToolRunRequest,
)

from ..core.errors import DomainError
from ..db.models import JobRow, StoredFile
from ..db.repos.owned import get_owned
from ..services import exports as exports_service
from ..services import operations as operations_service
from ..services import table_history as table_history_service
from ..services import tools as tools_service
from ..services import workbooks as wb_service


def make_import_handler(app_state: Any):  # type: ignore[no-untyped-def]
    async def handle(job: JobRow) -> str | None:
        settings = app_state.settings
        async with app_state.sessionmaker() as db:
            try:
                file = await get_owned(db, StoredFile, job.owner_id, job.payload["file_id"])
            except DomainError:
                raise DomainError("import_failed", "The uploaded file no longer exists.") from None
            row = await wb_service.import_file(
                db,
                app_state.services,
                app_state.copies,
                app_state.layout,
                owner_id=job.owner_id,
                file=file,
                time_limit=settings.import_timeout_seconds,
            )
            return str(row.id)

    return handle


def make_operation_handler(app_state: Any):  # type: ignore[no-untyped-def]
    async def handle(job: JobRow) -> str | None:
        if "table_tool_run" in job.payload:  # a saved tool on a Data Table: one version per step
            tseq = await table_history_service.run_tool(
                app_state,
                job.owner_id,
                job.payload["table_id"],
                job.payload["tool_id"],
                TableToolRunRequest.model_validate(job.payload["table_tool_run"]),
            )
            return str(tseq)
        if "tool_run" in job.payload:  # a saved tool: one history entry per step
            seq = await tools_service.run_tool(
                app_state,
                job.owner_id,
                job.payload["tool_id"],
                ToolRunRequest.model_validate(job.payload["tool_run"]),
            )
            return str(seq)
        req = OperationRequest.model_validate(job.payload["request"])
        if "table_id" in job.payload:  # an operation on a Data Table: a new version
            tseq = await table_history_service.run_operation(
                app_state, job.owner_id, job.payload["table_id"], req
            )
            return str(tseq)
        result = await operations_service.run_operation(
            app_state, job.owner_id, job.payload["doc_id"], req
        )
        return str(result.history_entry.seq)  # the job's result is the history entry it created

    return handle


def make_export_handler(app_state: Any):  # type: ignore[no-untyped-def]
    async def handle(job: JobRow) -> str | None:
        req = ExportRequest.model_validate(job.payload["request"])
        if "table_id" in job.payload:
            file_id, report = await exports_service.run_table_export(
                app_state, job.owner_id, job.payload["table_id"], req
            )
        else:
            file_id, report = await exports_service.run_export(
                app_state, job.owner_id, job.payload["doc_id"], req
            )
        async with app_state.sessionmaker() as db:  # keep the export report next to the job
            j = await db.get(JobRow, job.id)
            if j is not None:
                j.payload = {**j.payload, "report": report}
                await db.commit()
        return file_id  # the job's result is the stored file (GET /files/{id}/download)

    return handle
