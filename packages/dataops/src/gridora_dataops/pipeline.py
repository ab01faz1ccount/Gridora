"""run_pipeline: all-or-nothing, one OperationResult (own delta) per step, per-step undo.

Phase 1 (dry run, nothing written): every step is resolved, validated and planned on in-memory frames, chained exactly
as it will run; space checks for sheet writes use the current sheet. Phase 2 (commit): the steps are applied one by one
through the normal `apply`; if one fails unexpectedly the effects of the earlier steps are rolled back (table versions
and tables created by this run are discarded; sheet cells are restored value by value).
"""
from __future__ import annotations

from typing import Any, Optional

import polars as pl
from gridora_contracts.models import (
    CellPatchDelta,
    DataTableTarget,
    Delta,
    Operation,
    OperationResult,
    Pipeline,
    Range,
    SheetRangeTarget,
    TableVersionDelta,
    Target,
    ValidationError,
)
from gridora_contracts.protocols import ExecContext

from .errors import DataOpsError, pointer, verr
from .targets import check_write
from .tools import placeholders


def _prefixed(errs: list[ValidationError], i: int) -> list[ValidationError]:
    return [verr(e.code, pointer("steps", i) + e.path, e.message, e.hint) for e in errs]


def _fail(n: int, at: int, errs: list[ValidationError]) -> list[OperationResult]:
    out = []
    for j in range(n):
        if j == at:
            out.append(OperationResult(status="error", errors=errs))
        else:
            out.append(OperationResult(status="error", errors=[verr(
                "pipeline_aborted", pointer("steps", j), "the pipeline was aborted; nothing was changed")]))
    return out


def _restore_cells(ctx: ExecContext, delta: CellPatchDelta) -> None:
    """Write back the `before` cells run by run: only cells the step changed are touched (formulas elsewhere stay)."""
    by_row: dict[int, list[Any]] = {}
    for c in delta.before:
        by_row.setdefault(c.r, []).append(c)
    for r, cells in by_row.items():
        cells.sort(key=lambda c: c.c)
        run = [cells[0]]
        for c in [*cells[1:], None]:
            if c is not None and c.c == run[-1].c + 1:
                run.append(c)
                continue
            ctx.write_range(Range(sheet_id=delta.sheet_id, r0=r, c0=run[0].c, r1=r, c1=run[-1].c), [[x.v for x in run]])
            run = [c] if c is not None else []


def _rollback(ctx: ExecContext, applied: list[OperationResult]) -> bool:
    """Undo what earlier steps did. Returns False if some of it could not be undone."""
    store: Any = ctx.table_store() if any(isinstance(r.delta, TableVersionDelta) for r in applied) else None
    complete = True
    for res in reversed(applied):
        d: Optional[Delta] = res.delta
        try:
            if isinstance(d, TableVersionDelta) and store is not None:
                if d.from_version == 0:
                    store.discard_table(ctx.user_id, d.table_id)
                else:
                    store.discard_version(ctx.user_id, d.table_id, d.to_version)
            elif isinstance(d, CellPatchDelta):
                _restore_cells(ctx, d)
        except (DataOpsError, OSError):
            complete = False  # keep going: undo as much as possible
    return complete


def run_pipeline(ex: Any, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]:
    n = len(p.steps)
    if n == 0:
        return []
    if p.input_kind != target.kind:
        return _fail(n, 0, [verr("invalid_param", pointer("input_kind"), f"the pipeline expects a {p.input_kind}")])
    headers = set()
    for i, st in enumerate(p.steps):
        if next(placeholders(st.params), None) is not None:
            return _fail(n, i, [verr("invalid_param", pointer("steps", i, "params"), "unbound input: use bind_tool first")])
        spec = ex.registry.get(st.type)
        if spec is not None and spec.extra_inputs:
            return _fail(n, i, [verr("invalid_param", pointer("steps", i, "type"),
                                     f"'{st.type}' needs extra targets and cannot be a pipeline step")])
        if isinstance(target, SheetRangeTarget) and "has_header" in st.params:
            headers.add(bool(st.params["has_header"]))
            if len(headers) > 1:
                return _fail(n, i, [verr("invalid_param", pointer("steps", i, "params", "has_header"),
                                         "all steps on a sheet range must agree on has_header")])

    # ---------------------------------------------------------------- phase 1: dry run
    cur_frame: Optional[pl.DataFrame] = None
    kind = target.kind
    cur_range: Optional[Range] = target.range if isinstance(target, SheetRangeTarget) else None
    ranges: list[Optional[Range]] = []
    cur_target: Target = target
    try:
        for i, st in enumerate(p.steps):
            op = Operation(type=st.type, schema_version=st.schema_version, target=cur_target, params=st.params)
            spec, params, errs = ex._resolve(op)
            if errs or spec is None or params is None:
                return _fail(n, i, _prefixed(errs, i))
            if cur_frame is None:
                src = ex._load(spec, params, op, ctx)
            else:
                from .executor import _Source
                src = _Source(cur_frame, list(cur_frame.columns), spec.has_header(params))
            ranges.append(cur_range)
            frame, _w = ex._plan_from(spec, params, src, [])
            if kind == "sheet_range" and not (spec.creates_table or spec.sheet_output == "new_table"):
                assert cur_range is not None
                rows = frame.height + (1 if src.has_header else 0)
                check_write(ctx, cur_range, rows, frame.width, max_cells=ex.max_patch_cells)
                cur_range = Range(sheet_id=cur_range.sheet_id, r0=cur_range.r0, c0=cur_range.c0,
                                  r1=cur_range.r0 + max(rows, 1) - 1, c1=cur_range.c0 + max(frame.width, 1) - 1)
            elif spec.creates_table or (kind == "sheet_range" and spec.sheet_output == "new_table"):
                kind, cur_range = "data_table", None
                cur_target = DataTableTarget(table_id="__pending__")
            cur_frame = frame
    except DataOpsError as e:
        return _fail(n, i, _prefixed(e.errors, i))

    # ---------------------------------------------------------------- phase 2: commit
    results: list[OperationResult] = []
    cur_target = target
    kind = target.kind
    for i, st in enumerate(p.steps):
        if kind == "sheet_range" and ranges[i] is not None:
            cur_target = SheetRangeTarget(range=ranges[i])
        op = Operation(type=st.type, schema_version=st.schema_version, target=cur_target, params=st.params)
        res = ex.apply(op, ctx)
        if res.status != "ok":
            errs = _prefixed(res.errors, i)
            if not _rollback(ctx, results):
                errs.append(verr("rollback_incomplete", pointer("steps", i),
                                 "some earlier steps could not be undone; check the data and use the history"))
            return _fail(n, i, errs)
        results.append(res)
        if isinstance(res.output, DataTableTarget):
            cur_target, kind = res.output, "data_table"
    return results
