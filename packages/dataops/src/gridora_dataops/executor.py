"""DataOpsExecutor: implements the contract's OperationExecutor (M0: sheet-range path, no operations yet)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
from .errors import DataOpsError, NotImplementedYet, pointer, verr
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

    def _check_columns(self, spec: OperationSpec, params: ParamsModel, names: list[str]) -> list[ValidationError]:
        schema = spec.descriptor().params_schema
        out = []
        for ptr, col, column_of in column_refs(schema, params.model_dump(mode="json")):
            if column_of == "target" and col not in names:
                out.append(verr("unknown_column", ptr, f"column '{col}' does not exist", hint="; ".join(names[:20])))
        return out

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
        if isinstance(op.target, SheetRangeTarget):
            allow = (not spec.rewrites_cells) or getattr(params, "formulas", None) == "convert_to_values"
            sf = load_sheet_frame(ctx, op.target.range, spec.has_header(params), allow_formulas=allow)
            return _Source(sf.frame, sf.names, sf.has_header, sheet=sf)
        assert isinstance(op.target, DataTableTarget)
        store = self._store(ctx)
        owner = ctx.user_id
        wanted: int | None = getattr(op.target, "version", None)  # contract may add it (see PR note)
        frame, version = store.read_frame(owner, op.target.table_id, wanted)
        return _Source(frame, list(frame.columns), True,
                       table=_TableRef(store, owner, op.target.table_id, version, assumed=wanted is None))

    def _plan(self, op: Operation, ctx: ExecContext) -> tuple[OperationSpec, _Source, pl.DataFrame, list[Warning_]]:
        spec, params, errs = self._resolve(op)
        if errs or spec is None or params is None:
            raise DataOpsError("validation_failed", "operation parameters are invalid", errors=errs)
        src = self._load(spec, params, op, ctx)
        errs = self._check_columns(spec, params, src.names)
        if errs:
            raise DataOpsError("validation_failed", "operation parameters are invalid", errors=errs)
        out = spec.plan(src.frame, params, PlanEnv(has_header=src.has_header, column_names=src.names))
        warnings = list(out.warnings)
        if src.table is not None and src.table.assumed and len(src.table.store.versions(src.table.owner, src.table.table_id)) > 1:
            warnings.append(Warning_(code="table_version_assumed", severity="warn", location=src.table.table_id,
                                     message=f"the target named no version; the highest ({src.table.version}) was used"))
        return spec, src, out.frame, warnings

    # ------------------------------------------------------------ contract
    def validate(self, op: Operation, ctx: ExecContext | None = None) -> list[ValidationError]:
        spec, params, errs = self._resolve(op)
        if errs or spec is None or params is None or ctx is None:
            return errs
        try:
            src = self._load(spec, params, op, ctx)
        except DataOpsError as e:
            return e.errors
        return self._check_columns(spec, params, src.names)

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
            if src.table is not None:  # in-place on a data table: a new immutable version
                t = src.table
                dt = t.store.write_version(t.owner, t.table_id, frame, parent=t.version)
                return OperationResult(
                    status="ok", warnings=warnings,
                    affected=Affected(rows=frame.height, cells=frame.height * frame.width),
                    delta=TableVersionDelta(table_id=t.table_id, from_version=t.version, to_version=dt.version))
            assert src.sheet is not None
            if spec.sheet_output == "new_table":  # e.g. filter: the source rows are never lost
                store = self._store(ctx)
                name = catalog("fa").get(f"ops.{spec.type}.label", spec.type)
                dt = store.create_table(ctx.user_id, ctx.workspace_id, name, infer_table_frame(frame))
                return OperationResult(
                    status="ok", warnings=warnings, output=DataTableTarget(table_id=dt.id),
                    affected=Affected(rows=frame.height, cells=frame.height * frame.width),
                    delta=TableVersionDelta(table_id=dt.id, from_version=0, to_version=1))
            delta, cells = commit_sheet_frame(ctx, src.sheet, frame, max_cells=self.max_patch_cells)
        except DataOpsError as e:
            return OperationResult(status="error", errors=e.errors)
        return OperationResult(status="ok", affected=Affected(cells=cells, rows=frame.height), delta=delta,
                               warnings=warnings)

    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]:
        raise NotImplementedYet("run_pipeline (M5)")

    def chart_data(self, spec: ChartSpec, ctx: ExecContext) -> ChartData:
        raise NotImplementedYet("chart_data (M4)")

    def validate_tool(self, tool: Tool, target: Target, ctx: ExecContext | None = None) -> list[ValidationError]:
        raise NotImplementedYet("validate_tool (M5)")

    def bind_tool(self, tool: Tool, inputs: dict[str, Any]) -> Pipeline:
        raise NotImplementedYet("bind_tool (M5)")


def create_executor(config: Mapping[str, Any]) -> DataOpsExecutor:
    return DataOpsExecutor(max_patch_cells=int(config.get("max_patch_cells", DEFAULT_MAX_PATCH_CELLS)))
