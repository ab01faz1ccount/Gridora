"""DataOpsExecutor: implements the contract's OperationExecutor (M0: sheet-range path, no operations yet)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

import polars as pl
from gridora_contracts.models import (
    Affected,
    ChartData,
    ChartSpec,
    DataTableTarget,
    Operation,
    OperationDescriptor,
    OperationResult,
    Pipeline,
    PreviewResult,
    SheetRangeTarget,
    TableVersionDelta,
    Target,
    Tool,
    ValidationError,
    Warning_,
)
from gridora_contracts.protocols import ExecContext
from pydantic import ValidationError as PydanticValidationError

from .catalog import catalog
from .errors import DataOpsError, pointer, verr
from .registry import OperationRegistry, default_registry
from .schema import column_refs
from .spec import OperationSpec, ParamsModel, PlanEnv
from .tables.bridge import infer_table_frame
from .tables.store import ParquetTableStore
from .targets import SheetFrame, commit_sheet_frame, load_sheet_frame

DEFAULT_MAX_PATCH_CELLS = 200_000  # Phase 2 decision A2-Q5; configurable via create_executor(config)


def _json_value(x: Any) -> Any:
    return x.isoformat() if hasattr(x, "isoformat") else x


@dataclass
class _TableRef:
    store: ParquetTableStore
    owner: str
    table_id: str
    version: int
    assumed: bool  # the target did not say which version; the highest existing one was used


@dataclass
class _Source:
    frame: pl.DataFrame
    names: list[str]
    has_header: bool
    sheet: SheetFrame | None = None
    table: _TableRef | None = None


class DataOpsExecutor:
    def __init__(self, registry: OperationRegistry | None = None, *, max_patch_cells: int = DEFAULT_MAX_PATCH_CELLS) -> None:
        self.registry = registry if registry is not None else default_registry()
        self.max_patch_cells = max_patch_cells

    # ------------------------------------------------------------ describe
    def describe_all(self) -> list[OperationDescriptor]:
        return [s.descriptor() for s in self.registry.all()]

    # ------------------------------------------------------------ helpers
    def _resolve(self, op: Operation) -> tuple[OperationSpec | None, ParamsModel | None, list[ValidationError]]:
        spec = self.registry.get(op.type)
        if spec is None:
            return None, None, [verr("unknown_operation", pointer("type"), f"unknown operation '{op.type}'")]
        errs: list[ValidationError] = []
        if op.target.kind not in spec.targets:
            errs.append(verr("unsupported_target", pointer("target", "kind"),
                             f"'{op.type}' does not support target '{op.target.kind}'"))
        raw = dict(op.params)
        if op.schema_version < spec.schema_version:
            raw = spec.migrate(raw, op.schema_version)
        elif op.schema_version > spec.schema_version:
            errs.append(verr("invalid_param", pointer("schema_version"), "params schema_version is newer than supported"))
        try:
            params = spec.Params.model_validate(raw)
        except PydanticValidationError as e:
            for d in e.errors():
                code = "unknown_param" if d["type"] == "extra_forbidden" else "invalid_param"
                errs.append(verr(code, pointer("params", *d["loc"]), d["msg"]))
            return spec, None, errs
        errs.extend(spec.validate_static(params))
        return spec, params, errs

    def _check_columns(self, spec: OperationSpec, params: ParamsModel, names: list[str],
                       extra_names: Optional[list[list[str]]] = None) -> list[ValidationError]:
        schema = spec.descriptor().params_schema
        out = []
        for ptr, col, column_of in column_refs(schema, params.model_dump(mode="json")):
            pool: Optional[list[str]] = names
            if column_of.startswith("extra_targets/"):
                i = int(column_of.split("/")[1])
                pool = (extra_names or [])[i] if i < len(extra_names or []) else None
            if pool is not None and col not in pool:
                out.append(verr("unknown_column", ptr, f"column '{col}' does not exist", hint="; ".join(pool[:20])))
        return out

    def _load_target(self, target: Target, ctx: ExecContext, *, has_header: bool = True, allow_formulas: bool = False,
                     lenient: bool = False) -> _Source:
        if isinstance(target, SheetRangeTarget):
            sf = load_sheet_frame(ctx, target.range, has_header, allow_formulas=allow_formulas, lenient=lenient)
            return _Source(sf.frame, sf.names, sf.has_header, sheet=sf)
        assert isinstance(target, DataTableTarget)
        store = self._store(ctx)
        wanted: Optional[int] = getattr(target, "version", None)
        frame, version = store.read_frame(ctx.user_id, target.table_id, wanted)
        return _Source(frame, list(frame.columns), True,
                       table=_TableRef(store, ctx.user_id, target.table_id, version, assumed=wanted is None))

    def _load_extras(self, spec: OperationSpec, op: Operation, ctx: ExecContext) -> list[_Source]:
        if len(op.extra_targets) != spec.extra_inputs:
            raise DataOpsError("invalid_param", f"'{op.type}' needs {spec.extra_inputs} extra target(s)",
                               path=pointer("extra_targets"))
        return [self._load_target(t, ctx, allow_formulas=True, lenient=True) for t in op.extra_targets]

    @staticmethod
    def _store(ctx: ExecContext) -> ParquetTableStore:
        try:
            store = ctx.table_store()
        except NotImplementedError:
            store = None
        if not isinstance(store, ParquetTableStore):
            raise DataOpsError("not_implemented", "no dataops table store is available in this context")
        return store

    def _load(self, spec: OperationSpec, params: ParamsModel, op: Operation, ctx: ExecContext) -> _Source:
        allow = (not spec.rewrites_cells) or getattr(params, "formulas", None) == "convert_to_values"
        return self._load_target(op.target, ctx, has_header=spec.has_header(params), allow_formulas=allow)

    def _plan_from(self, spec: OperationSpec, params: ParamsModel, src: _Source,
                   extras: list[_Source]) -> tuple[pl.DataFrame, list[Warning_]]:
        errs = self._check_columns(spec, params, src.names, [e.names for e in extras])
        if errs:
            raise DataOpsError("validation_failed", "operation parameters are invalid", errors=errs)
        out = spec.plan(src.frame, params, PlanEnv(has_header=src.has_header, column_names=src.names,
                                                   extra_frames=[e.frame for e in extras]))
        warnings = list(out.warnings)
        if src.table is not None and src.table.assumed and len(src.table.store.versions(src.table.owner, src.table.table_id)) > 1:
            warnings.append(Warning_(code="table_version_assumed", severity="warn", location=src.table.table_id,
                                     message=f"the target named no version; the highest ({src.table.version}) was used"))
        return out.frame, warnings

    def _plan(self, op: Operation, ctx: ExecContext) -> tuple[OperationSpec, _Source, pl.DataFrame, list[Warning_]]:
        spec, params, errs = self._resolve(op)
        if errs or spec is None or params is None:
            raise DataOpsError("validation_failed", "operation parameters are invalid", errors=errs)
        src = self._load(spec, params, op, ctx)
        extras = self._load_extras(spec, op, ctx)
        frame, warnings = self._plan_from(spec, params, src, extras)
        return spec, src, frame, warnings

    # ------------------------------------------------------------ contract
    def validate(self, op: Operation, ctx: ExecContext | None = None) -> list[ValidationError]:
        spec, params, errs = self._resolve(op)
        if errs or spec is None or params is None or ctx is None:
            return errs
        try:
            src = self._load(spec, params, op, ctx)
            extras = self._load_extras(spec, op, ctx)
        except DataOpsError as e:
            return e.errors
        return self._check_columns(spec, params, src.names, [x.names for x in extras])

    def preview(self, op: Operation, ctx: ExecContext, limit: int) -> PreviewResult:
        """Never mutates: no write_range, no store writes. Raises DataOpsError(validation_failed) on bad input."""
        spec, _src, frame, warnings = self._plan(op, ctx)
        if not spec.supports_preview:
            raise DataOpsError("not_implemented", f"'{op.type}' has no preview")
        head = frame.head(max(limit, 0))
        return PreviewResult(columns=list(frame.columns),
                             rows=[[_json_value(x) for x in r] for r in head.iter_rows()],
                             total_rows=frame.height, warnings=warnings)

    def apply(self, op: Operation, ctx: ExecContext) -> OperationResult:
        try:
            spec, src, frame, warnings = self._plan(op, ctx)
            if spec.creates_table or (src.sheet is not None and spec.sheet_output == "new_table"):
                store = self._store(ctx)  # the source is never modified; the result is a NEW table
                name = catalog("fa").get(f"ops.{spec.type}.label", spec.type)
                dt = store.create_table(ctx.user_id, ctx.workspace_id, name, infer_table_frame(frame))
                return OperationResult(
                    status="ok", warnings=warnings, output=DataTableTarget(table_id=dt.id),
                    affected=Affected(rows=frame.height, cells=frame.height * frame.width),
                    delta=TableVersionDelta(table_id=dt.id, from_version=0, to_version=1))
            if src.table is not None:  # in-place on a data table: a new immutable version
                t = src.table
                dt = t.store.write_version(t.owner, t.table_id, frame, parent=t.version)
                return OperationResult(
                    status="ok", warnings=warnings,
                    affected=Affected(rows=frame.height, cells=frame.height * frame.width),
                    delta=TableVersionDelta(table_id=t.table_id, from_version=t.version, to_version=dt.version))
            assert src.sheet is not None
            delta, cells = commit_sheet_frame(ctx, src.sheet, frame, max_cells=self.max_patch_cells)
        except DataOpsError as e:
            return OperationResult(status="error", errors=e.errors)
        return OperationResult(status="ok", affected=Affected(cells=cells, rows=frame.height), delta=delta,
                               warnings=warnings)

    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]:
        from .pipeline import run_pipeline

        return run_pipeline(self, p, target, ctx)

    def chart_data(self, spec: ChartSpec, ctx: ExecContext) -> ChartData:
        """Plain values for the web app (no ECharts types). A sheet source is read with its first row as header."""
        from .charts import build_chart_data

        src = self._load_target(spec.source, ctx, has_header=True, allow_formulas=True, lenient=True)
        return build_chart_data(spec, src.frame)

    def validate_tool(self, tool: Tool, target: Target, ctx: ExecContext | None = None) -> list[ValidationError]:
        from .tools import validate_tool

        return validate_tool(self, tool, target, ctx)

    def bind_tool(self, tool: Tool, inputs: dict[str, Any]) -> Pipeline:
        from .tools import bind_tool

        return bind_tool(tool, inputs)


def create_executor(config: Mapping[str, Any]) -> DataOpsExecutor:
    return DataOpsExecutor(max_patch_cells=int(config.get("max_patch_cells", DEFAULT_MAX_PATCH_CELLS)))
