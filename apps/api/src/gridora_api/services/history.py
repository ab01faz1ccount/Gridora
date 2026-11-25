"""Cell edits, undo/redo and replay (docs/DATA_MODEL.md section 6).

Invariants:
- Every mutation runs inside one DB transaction that holds a row lock on the workbook, so two
  requests (or tabs, or processes) never interleave, and `base_seq` is checked under the lock.
- `seq` is issued from a counter that never goes backwards; a stale client can never mistake a
  different entry for the one it saw. The HEAD is the highest seq among entries that are not undone.
- Active entries are a prefix of the stack, undone entries its tail; a new edit deletes the tail.
- If anything fails after the engine already changed, the working copy is DROPPED: it is rebuilt
  from the stored file plus the committed history on next use: memory never disagrees with the DB.
- Deltas carry the PUBLIC sheet ids (what clients and URLs use); they are translated to the engine's
  ids when applied (Entry.sheet_map).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from gridora_contracts.models import (
    Cell,
    CellEdit,
    CellEditRequest,
    CellPatchDelta,
    CellsChangedResult,
    Delta,
    ErrorDetail,
    HistoryEntry,
    Operation,
    Range,
    SheetCells,
    SheetRangeTarget,
    SheetStructureDelta,
    StructureRequest,
    Workbook,
)
from gridora_contracts.protocols import StructureEngine
from pydantic import TypeAdapter
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..composition.wiring import Services
from ..core.errors import DomainError
from ..db.models import HistoryRow, WorkbookRow
from ..db.repos.owned import parse_id
from .working_copies import Entry, WorkingCopies

DELTA = TypeAdapter(Delta)
MAX_EDITS_PER_REQUEST = 50_000
MAX_HISTORY_ENTRIES = (
    5_000  # until saving can compact history (E6/PR 12); bounds DB and replay time
)


# ------------------------------------------------------------------ sheet ids ----
def delta_with_sheet(delta: Delta, mapping: dict[str, str]) -> Delta:
    """Rewrite the sheet id of a delta through `mapping` (public->engine or engine->public)."""
    sid = getattr(delta, "sheet_id", None)
    if isinstance(sid, str) and sid in mapping:
        return delta.model_copy(update={"sheet_id": mapping[sid]})
    return delta


def _engine_delta(delta: Delta, entry: Entry) -> Delta:
    return delta_with_sheet(delta, entry.sheet_map)


def _public_delta(delta: Delta, entry: Entry) -> Delta:
    return delta_with_sheet(delta, {eng: pub for pub, eng in entry.sheet_map.items()})


# ----------------------------------------------------------------- DB helpers ----
async def lock_workbook(db: AsyncSession, owner_id: uuid.UUID, raw_id: str) -> WorkbookRow:
    row = (
        await db.execute(
            select(WorkbookRow)
            .where(WorkbookRow.id == parse_id(raw_id), WorkbookRow.owner_id == owner_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise DomainError("not_found")
    return row


async def head_seq(db: AsyncSession, doc_id: uuid.UUID) -> int:
    v = (
        await db.execute(
            select(func.max(HistoryRow.seq)).where(
                HistoryRow.document_id == doc_id, HistoryRow.undone.is_(False)
            )
        )
    ).scalar_one()
    return int(v or 0)


async def active_deltas_since(db: AsyncSession, row: WorkbookRow) -> list[tuple[int, Delta]]:
    rows = (
        await db.execute(
            select(HistoryRow.seq, HistoryRow.delta_json)
            .where(
                HistoryRow.document_id == row.id,
                HistoryRow.undone.is_(False),
                HistoryRow.seq > row.last_saved_seq,
            )
            .order_by(HistoryRow.seq)
        )
    ).all()
    return [(int(seq), DELTA.validate_python(d)) for seq, d in rows]


def check_base(base_seq: int | None, head: int) -> None:
    if base_seq is not None and base_seq != head:
        raise DomainError(
            "version_conflict",
            details=[
                ErrorDetail(
                    code="history.stale", path="/base_seq", message=f"the current head is {head}"
                )
            ],
        )


def entry_out(h: HistoryRow) -> HistoryEntry:
    return HistoryEntry(
        id=str(h.id),
        document_id=str(h.document_id),
        seq=h.seq,
        operation=Operation.model_validate(h.operation_json),
        delta=DELTA.validate_python(h.delta_json),
        label=h.label,
        created_at=h.created_at,
        undone=h.undone,
    )


def _cells_of(delta: Delta, *, after: bool) -> list[Cell]:
    if isinstance(delta, CellPatchDelta):
        return list(delta.after if after else delta.before)
    return []


def others_of(delta: Delta, *, after: bool = True) -> list[SheetCells]:
    """Cells of other sheets changed by cross-sheet recalculation (contract 0.5.0)."""
    if not isinstance(delta, CellPatchDelta):
        return []
    return [
        SheetCells(sheet_id=o.sheet_id, cells=list(o.after if after else o.before))
        for o in delta.others
    ]


def _sheet_of(delta: Delta, fallback: str) -> str:
    sid = getattr(delta, "sheet_id", None)
    return sid if isinstance(sid, str) else fallback


async def commit_or_drop(
    db: AsyncSession, copies: WorkingCopies, doc_id: uuid.UUID, ok_after_engine: bool = True
) -> None:
    try:
        await db.commit()
    except BaseException:
        copies.drop(str(doc_id))  # the engine already changed; rebuild from committed state
        raise


# ----------------------------------------------------------------------- edit ----
async def apply_edits(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    row: WorkbookRow,
    entry: Entry,
    sheet_id: str,
    req: CellEditRequest,
) -> CellsChangedResult:
    if not req.edits:
        raise DomainError(
            "validation_failed",
            details=[ErrorDetail(code="edits.empty", path="/edits", message="no edits given")],
        )
    if len(req.edits) > MAX_EDITS_PER_REQUEST:
        raise DomainError(
            "validation_failed",
            details=[
                ErrorDetail(
                    code="edits.too_many",
                    path="/edits",
                    message=f"at most {MAX_EDITS_PER_REQUEST} edits per request",
                )
            ],
        )
    head = await head_seq(db, row.id)
    check_base(req.base_seq, head)
    total = (
        await db.execute(
            select(func.count()).select_from(HistoryRow).where(HistoryRow.document_id == row.id)
        )
    ).scalar_one()
    if total >= MAX_HISTORY_ENTRIES:
        raise DomainError(
            "operation_conflict",
            "The undo history is full.",
            details=[
                ErrorDetail(code="history.full", message="save the workbook to start a new history")
            ],
        )

    engine_sheet = entry.to_engine(sheet_id)
    try:
        engine_delta = await copies.call(
            entry, services.engine.apply_cell_edits, entry.handle, engine_sheet, list(req.edits)
        )
    except BaseException:
        raise  # the engine's edits are atomic: nothing changed
    delta = _public_delta(engine_delta, entry)

    r_hi = max(e.r for e in req.edits)
    c_hi = max(e.c for e in req.edits)
    op = Operation(
        type="cell_edit",
        target=SheetRangeTarget(
            range=Range(
                sheet_id=sheet_id,
                r0=min(e.r for e in req.edits),
                c0=min(e.c for e in req.edits),
                r1=r_hi,
                c1=c_hi,
            )
        ),
        params={"count": len(req.edits)},
    )
    h = await record_entry(db, copies, row, op, delta, "history.cell_edit")
    grow_dimensions(row, sheet_id, r_hi + 1, c_hi + 1)
    await commit_or_drop(db, copies, row.id)
    return CellsChangedResult(
        history_entry=entry_out(h), sheet_id=sheet_id, cells=_cells_of(delta, after=True),
        others=others_of(delta),
    )


async def record_entry(
    db: AsyncSession,
    copies: WorkingCopies,
    row: WorkbookRow,
    op: Operation,
    delta: Delta,
    label: str,
) -> HistoryRow:
    """Add one history entry (discarding the redo tail); the caller commits via _commit_or_drop.
    The engine has ALREADY changed: if the bookkeeping fails, the working copy is dropped."""
    try:
        await db.execute(
            delete(HistoryRow).where(HistoryRow.document_id == row.id, HistoryRow.undone.is_(True))
        )
        row.seq_counter += 1
        h = HistoryRow(
            document_id=row.id,
            owner_id=row.owner_id,
            seq=row.seq_counter,
            operation_json=op.model_dump(mode="json"),
            delta_json=delta.model_dump(mode="json"),
            label=label,
            undone=False,
        )
        db.add(h)
        await db.flush()
        await db.refresh(h)
    except BaseException:
        copies.drop(str(row.id))
        raise
    return h


def adjust_dimensions(row: WorkbookRow, delta: Delta, *, undo: bool) -> None:
    """Row/column counts follow an insert or delete (and its undo/redo)."""
    if not isinstance(delta, SheetStructureDelta) or delta.change.get("type") != "axis_shift":
        return
    ch = delta.change
    n = int(ch["count"]) * (1 if (ch["op"] == "insert") != undo else -1)
    key = "row_count" if ch["axis"] == "row" else "col_count"
    meta: dict[str, Any] = dict(row.meta_json)
    sheets = [dict(x) for x in meta.get("sheets", [])]
    for x in sheets:
        if x["id"] == delta.sheet_id:
            x[key] = max(int(x[key]) + n, 0)
    meta["sheets"] = sheets
    row.meta_json = meta


async def apply_structure(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    row: WorkbookRow,
    entry: Entry,
    sheet_id: str,
    req: StructureRequest,
) -> CellsChangedResult:
    """Insert or delete rows/columns: one history entry. The whole sheet moves, so the answer
    carries no cells: the client sees a non-cell_patch delta and reloads the sheet."""
    head = await head_seq(db, row.id)
    check_base(req.base_seq, head)
    total = (
        await db.execute(
            select(func.count()).select_from(HistoryRow).where(HistoryRow.document_id == row.id)
        )
    ).scalar_one()
    if total >= MAX_HISTORY_ENTRIES:
        raise DomainError(
            "operation_conflict",
            "The undo history is full.",
            details=[
                ErrorDetail(code="history.full", message="save the workbook to start a new history")
            ],
        )
    change = {
        "type": "axis_shift", "sheet_id": entry.to_engine(sheet_id), "axis": req.axis, "op": req.op,
        "at": req.at, "count": req.count,
    }
    engine_delta = await copies.call(
        entry, cast(StructureEngine, services.engine).apply_structure_change, entry.handle, change
    )
    delta = _public_delta(engine_delta, entry)
    if req.axis == "row":
        rng = Range(sheet_id=sheet_id, r0=req.at, c0=0, r1=req.at + req.count - 1, c1=0)
    else:
        rng = Range(sheet_id=sheet_id, r0=0, c0=req.at, r1=0, c1=req.at + req.count - 1)
    op = Operation(
        type="structure_change", target=SheetRangeTarget(range=rng),
        params={"axis": req.axis, "op": req.op, "at": req.at, "count": req.count},
    )
    h = await record_entry(db, copies, row, op, delta, f"history.{req.op}_{req.axis}s")
    adjust_dimensions(row, delta, undo=False)
    await commit_or_drop(db, copies, row.id)
    return CellsChangedResult(history_entry=entry_out(h), sheet_id=sheet_id, cells=[])


def grow_dimensions(row: WorkbookRow, sheet_id: str, rows: int, cols: int) -> None:
    """Sheet dimensions only grow in v1 (an edit past the end; undo does not shrink)."""
    meta: dict[str, Any] = dict(row.meta_json)
    sheets = [dict(s) for s in meta.get("sheets", [])]
    for s in sheets:
        if s["id"] == sheet_id:
            s["row_count"] = max(int(s["row_count"]), rows)
            s["col_count"] = max(int(s["col_count"]), cols)
    meta["sheets"] = sheets
    row.meta_json = meta  # reassign: SQLAlchemy does not see in-place JSON mutation


# ------------------------------------------------------------------ undo/redo ----
async def _step(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    row: WorkbookRow,
    entry: Entry,
    *,
    undo: bool,
    base_seq: int | None,
) -> CellsChangedResult:
    head = await head_seq(db, row.id)
    check_base(base_seq, head)
    if undo:
        stmt = (
            select(HistoryRow)
            .where(HistoryRow.document_id == row.id, HistoryRow.undone.is_(False))
            .order_by(HistoryRow.seq.desc())
            .limit(1)
        )
    else:
        stmt = (
            select(HistoryRow)
            .where(HistoryRow.document_id == row.id, HistoryRow.undone.is_(True))
            .order_by(HistoryRow.seq)
            .limit(1)
        )
    h = (await db.execute(stmt)).scalar_one_or_none()
    if h is None:
        code = "history.nothing_to_undo" if undo else "history.nothing_to_redo"
        raise DomainError("operation_conflict", details=[ErrorDetail(code=code, message=code)])
    delta = DELTA.validate_python(h.delta_json)
    await copies.call(
        entry, services.engine.apply_delta, entry.handle, _engine_delta(delta, entry), inverse=undo
    )
    try:
        adjust_dimensions(row, delta, undo=undo)
        h.undone = undo
        await db.flush()
        await db.refresh(h)
    except BaseException:
        copies.drop(str(row.id))
        raise
    await commit_or_drop(db, copies, row.id)
    sheet = _sheet_of(delta, next(iter(entry.sheet_map), ""))
    return CellsChangedResult(
        history_entry=entry_out(h), sheet_id=sheet, cells=_cells_of(delta, after=not undo),
        others=others_of(delta, after=not undo),
    )


async def undo(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    row: WorkbookRow,
    entry: Entry,
    base_seq: int | None,
) -> CellsChangedResult:
    return await _step(db, services, copies, row, entry, undo=True, base_seq=base_seq)


async def redo(
    db: AsyncSession,
    services: Services,
    copies: WorkingCopies,
    row: WorkbookRow,
    entry: Entry,
    base_seq: int | None,
) -> CellsChangedResult:
    return await _step(db, services, copies, row, entry, undo=False, base_seq=base_seq)


# --------------------------------------------------------------------- listing ----
async def list_entries(
    db: AsyncSession, doc_id: uuid.UUID, cursor: int | None, limit: int
) -> tuple[list[HistoryEntry], str | None]:
    stmt = select(HistoryRow).where(HistoryRow.document_id == doc_id)
    if cursor is not None:
        stmt = stmt.where(HistoryRow.seq < cursor)
    rows = (await db.execute(stmt.order_by(HistoryRow.seq.desc()).limit(limit + 1))).scalars().all()
    more = len(rows) > limit
    page = rows[:limit]
    return [entry_out(h) for h in page], (str(page[-1].seq) if more and page else None)


def meta_workbook(row: WorkbookRow) -> Workbook:
    return Workbook.model_validate(row.meta_json)


_ = CellEdit  # (re-exported type used by routers)
