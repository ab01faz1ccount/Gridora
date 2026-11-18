"""Job handlers. They get the app state through closures built in main.py (no globals)."""

from __future__ import annotations

from typing import Any

from gridora_contracts.models import OperationRequest

from ..core.errors import DomainError
from ..db.models import JobRow, StoredFile
from ..db.repos.owned import get_owned
from ..services import operations as operations_service
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
        req = OperationRequest.model_validate(job.payload["request"])
        result = await operations_service.run_operation(
            app_state, job.owner_id, job.payload["doc_id"], req
        )
        return str(result.history_entry.seq)  # the job's result is the history entry it created

    return handle
