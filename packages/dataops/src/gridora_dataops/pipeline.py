"""run_pipeline: all-or-nothing, one OperationResult (own delta) per step, per-step undo.

Phase 1 (dry run, nothing written): every step is resolved, validated and planned on in-memory frames, chained exactly
as it will run; space checks for sheet writes use the current sheet. Phase 2 (commit): the steps are applied one by one
through the normal `apply`; if one fails unexpectedly the effects of the earlier steps are rolled back (table versions
and tables created by this run are discarded; sheet cells are restored value by value).
"""
from __future__ import annotations

from dataclasses import dataclass
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
from .executor import _Source, _TableRef
from .tables.bridge import infer_table_frame
from .tables.frames import normalize_frame
from .targets import SheetFrame, check_write
from .tools import placeholders


@dataclass
class _Plan:
    """One planned step: what phase 1 decided, kept so phase 2 can commit it without re-reading."""

    spec: Any
    frame: Optional[pl.DataFrame]
    warnings: list[Any]
    kind: str
    range: Optional[Range]
    names: list[str]
    exact: bool
    has_header: bool
    table_ref: Any = None


def sheet_roundtrip(frame: pl.DataFrame) -> pl.DataFrame:
    """The frame a re-read of the just-written range would give: numbers are floats, NaN and all-empty columns are
    empty/text, header names are stripped and made unique. Keeps hand-off results identical to re-reading."""
    exprs = []
    for name, dtype in frame.schema.items():
        c = pl.col(name)
        if dtype.is_integer() or dtype.is_float():
            exprs.append(c.cast(pl.Float64).fill_nan(None))
        elif isinstance(dtype, pl.Datetime):
            exprs.append(c.cast(pl.Datetime("us")))
        elif dtype not in (pl.String, pl.Boolean, pl.Date):
            exprs.append(c.cast(pl.String))
    out = frame.with_columns(exprs) if exprs else frame
    out = out.with_columns([pl.col(c).cast(pl.String) for c in out.columns if out[c].null_count() == out.height and out[c].dtype != pl.String])
    names = [(n.strip() or f"column_{i + 1}") for i, n in enumerate(out.columns)]
    seen: dict[str, int] = {}
    final = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        final.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out.rename(dict(zip(out.columns, final, strict=True))) if final != list(out.columns) else out


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
        except Exception:  # noqa: BLE001 - the context may raise its own typed errors; keep undoing as much as possible
            complete = False
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
    plans: list[_Plan] = []
    cur_frame: Optional[pl.DataFrame] = None
    kind = target.kind
    cur_range: Optional[Range] = target.range if isinstance(target, SheetRangeTarget) else None
    cur_target: Target = target
    names_before: list[str] = []
    exact_before = True
    table_ref: Any = None
    total_bytes = 0
    keep = ex.pipeline_handoff
    try:
        for i, st in enumerate(p.steps):
            op = Operation(type=st.type, schema_version=st.schema_version, target=cur_target, params=st.params)
            spec, params, errs = ex._resolve(op)
            if errs or spec is None or params is None:
                return _fail(n, i, _prefixed(errs, i))
            if cur_frame is None:
                src = ex._load(spec, params, op, ctx)
                names_before = list(src.names)
                exact_before = src.sheet.header_exact if src.sheet is not None else True
                table_ref = src.table
            else:
                src = _Source(cur_frame, names_before, spec.has_header(params))
            frame, warns = ex._plan_from(spec, params, src, [])
            plans.append(_Plan(spec, frame, warns, kind, cur_range, list(names_before), exact_before, src.has_header,
                               table_ref if i == 0 else None))
            total_bytes += frame.estimated_size()
            if total_bytes > ex.handoff_max_bytes:
                keep = False  # too big to hold: re-read between steps instead
            if kind == "sheet_range" and not (spec.creates_table or spec.sheet_output == "new_table"):
                assert cur_range is not None
                rows = frame.height + (1 if src.has_header else 0)
                check_write(ctx, cur_range, rows, frame.width, max_cells=ex.max_patch_cells, columnar=ex.columnar)
                cur_range = Range(sheet_id=cur_range.sheet_id, r0=cur_range.r0, c0=cur_range.c0,
                                  r1=cur_range.r0 + max(rows, 1) - 1, c1=cur_range.c0 + max(frame.width, 1) - 1)
                cur_frame = sheet_roundtrip(frame)
                exact_before = list(frame.columns) == list(cur_frame.columns)
            elif spec.creates_table or (kind == "sheet_range" and spec.sheet_output == "new_table"):
                kind, cur_range = "data_table", None
                cur_target = DataTableTarget(table_id="__pending__")
                cur_frame, exact_before = normalize_frame(infer_table_frame(frame)), True
            else:
                cur_frame, exact_before = normalize_frame(frame), True
            names_before = list(cur_frame.columns)
    except DataOpsError as e:
        return _fail(n, i, _prefixed(e.errors, i))
    if not keep:
        for pl_ in plans:
            pl_.frame = None  # release the memory; the commit re-reads

    # ---------------------------------------------------------------- phase 2: commit
    results: list[OperationResult] = []
    cur_target = target
    kind = target.kind
    store: Any = plans[0].table_ref.store if plans[0].table_ref is not None else None
    ref: Any = plans[0].table_ref
    for i, st in enumerate(p.steps):
        try:
            if keep and plans[i].frame is not None:  # in-memory hand-off: commit the frame planned in phase 1
                pl_ = plans[i]
                if pl_.kind == "sheet_range":
                    assert pl_.frame is not None and pl_.range is not None
                    sf = SheetFrame(pl_.frame, pl_.range, pl_.has_header, pl_.names, 0, 0, header_exact=pl_.exact)
                    res = ex._commit_frame(pl_.spec, pl_.frame, pl_.warnings, ctx, table=None, sheet=sf)
                else:
                    res = ex._commit_frame(pl_.spec, pl_.frame, pl_.warnings, ctx, table=ref, sheet=None)
            else:  # re-read between steps (memory guard or `pipeline_handoff=False`)
                if kind == "sheet_range" and plans[i].range is not None:
                    cur_target = SheetRangeTarget(range=plans[i].range)
                op = Operation(type=st.type, schema_version=st.schema_version, target=cur_target, params=st.params)
                res = ex.apply(op, ctx)
        except DataOpsError as e:
            res = OperationResult(status="error", errors=e.errors)
        except Exception:
            _rollback(ctx, results)  # an error of the context itself (e.g. the API's history-cap error) propagates,
            raise                    # but never with earlier steps left applied
        if res.status != "ok":
            errs = _prefixed(res.errors, i)
            if not _rollback(ctx, results):
                errs.append(verr("rollback_incomplete", pointer("steps", i),
                                 "some earlier steps could not be undone; check the data and use the history"))
            return _fail(n, i, errs)
        results.append(res)
        if isinstance(res.delta, TableVersionDelta):  # name the exact version for the next step (no 'highest' guess)
            cur_target = DataTableTarget(table_id=res.delta.table_id, version=res.delta.to_version)
            kind = "data_table"
            store = store or ex._store(ctx)
            ref = _TableRef(store, ctx.user_id, res.delta.table_id, res.delta.to_version, assumed=False)
        elif isinstance(res.output, DataTableTarget):
            cur_target, kind = res.output, "data_table"
    return results
