"""STUB OperationExecutor + TableStore. NOT the real dataops package.

Exists so the web app can build the descriptor-driven form, preview, destructive-confirm and
undo flows. Implements three operations over sheet ranges only (sort, find_replace,
remove_duplicates). No data tables, no Polars/DuckDB, no Persian-aware collation (plain
case-folded comparison), no pipelines beyond sequential application.

The `x-gridora-widget` keyword below is a PLACEHOLDER until Agent 2 publishes
packages/dataops/docs/PARAMS_SCHEMA.md; the web renderer will follow that document.

Replaced by gridora_dataops via GRIDORA_DATAOPS=real (composition/wiring.py).
"""

from __future__ import annotations

from typing import Any

from gridora_contracts.models import (
    Affected,
    BoolValue,
    Cell,
    CellValue,
    ChartData,
    ChartSpec,
    DataTable,
    Delta,
    NumValue,
    Operation,
    OperationDescriptor,
    OperationResult,
    Pipeline,
    PreviewResult,
    Range,
    SheetRangeTarget,
    StrValue,
    Target,
    Tool,
    ValidationError,
    Warning_,
)
from gridora_contracts.protocols import ExecContext

from ...core.errors import DomainError

PREVIEW_MAX = 200


def _col_param(desc: str) -> dict[str, Any]:
    return {
        "type": "integer",
        "minimum": 0,
        "description": desc,
        "x-gridora-widget": "column",  # placeholder vocabulary (see module docstring)
    }


DESCRIPTORS: list[OperationDescriptor] = [
    OperationDescriptor(
        type="sort",
        label="ops.sort.label",
        category="ops.category.order",
        description="ops.sort.description",
        targets=["sheet_range"],
        destructive=False,
        supports_preview=True,
        params_schema={
            "type": "object",
            "required": ["columns"],
            "properties": {
                "has_header": {"type": "boolean", "default": True},
                "columns": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["column"],
                        "properties": {
                            "column": _col_param("column index inside the range"),
                            "descending": {"type": "boolean", "default": False},
                        },
                    },
                },
            },
        },
    ),
    OperationDescriptor(
        type="find_replace",
        label="ops.find_replace.label",
        category="ops.category.clean",
        description="ops.find_replace.description",
        targets=["sheet_range"],
        destructive=True,
        supports_preview=True,
        params_schema={
            "type": "object",
            "required": ["find"],
            "properties": {
                "find": {"type": "string", "minLength": 1},
                "replace": {"type": "string", "default": ""},
                "match_case": {"type": "boolean", "default": False},
                "whole_cell": {"type": "boolean", "default": False},
            },
        },
    ),
    OperationDescriptor(
        type="remove_duplicates",
        label="ops.remove_duplicates.label",
        category="ops.category.clean",
        description="ops.remove_duplicates.description",
        targets=["sheet_range"],
        destructive=True,
        supports_preview=True,
        params_schema={
            "type": "object",
            "properties": {
                "has_header": {"type": "boolean", "default": True},
                "columns": {
                    "type": "array",
                    "items": _col_param("column index inside the range"),
                    "description": "empty = all columns",
                },
            },
        },
    ),
]
_BY_TYPE = {d.type: d for d in DESCRIPTORS}


def _raw(c: Cell | None) -> Any:
    v = c.v if c else None
    if isinstance(v, NumValue):
        return v.n
    if isinstance(v, StrValue):
        return v.s
    if isinstance(v, BoolValue):
        return v.b
    return None if v is None else v.model_dump()


def _val(c: Cell | None) -> CellValue | None:
    return c.v if c else None


def _sort_key(v: Any) -> tuple[int, Any]:
    if v is None:
        return (3, 0)
    if isinstance(v, bool):
        return (2, v)
    if isinstance(v, (int, float)):
        return (0, v)
    return (1, str(v).casefold())  # no Persian-aware collation in the stub


def _sorted_by(body: list[list[Cell | None]], col: int, desc: bool) -> list[list[Cell | None]]:
    return sorted(body, key=lambda row: _sort_key(_raw(row[col])), reverse=desc)


def _err(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code=code, path=path, message=message)


def _range_of(op: Operation) -> Range | None:
    return op.target.range if isinstance(op.target, SheetRangeTarget) else None


class StubExecutor:
    def describe_all(self) -> list[OperationDescriptor]:
        return list(DESCRIPTORS)

    # ----------------------------------------------------------- validation ----
    def validate(self, op: Operation, ctx: ExecContext | None = None) -> list[ValidationError]:
        if op.type not in _BY_TYPE:
            return [_err("operation.unknown", "/type", f"unknown operation {op.type!r}")]
        rng = _range_of(op)
        if rng is None:
            return [_err("target.unsupported", "/target", "only sheet ranges are supported")]
        if op.extra_targets:
            return [
                _err("target.unexpected", "/extra_targets", "this operation takes no extra targets")
            ]
        p = op.params
        width = rng.c1 - rng.c0 + 1
        errs: list[ValidationError] = []
        if op.type == "sort":
            cols = p.get("columns")
            if not isinstance(cols, list) or not cols:
                errs.append(_err("param.required", "/params/columns", "choose at least one column"))
            else:
                for i, item in enumerate(cols):
                    c = item.get("column") if isinstance(item, dict) else None
                    if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c < width:
                        errs.append(
                            _err(
                                "param.range",
                                f"/params/columns/{i}/column",
                                "column is outside the selected range",
                            )
                        )
        elif op.type == "find_replace":
            f = p.get("find")
            if not isinstance(f, str) or not f:
                errs.append(_err("param.required", "/params/find", "text to find is required"))
            if not isinstance(p.get("replace", ""), str):
                errs.append(_err("param.type", "/params/replace", "must be text"))
        elif op.type == "remove_duplicates":
            cols = p.get("columns", [])
            if not isinstance(cols, list) or any(
                not isinstance(c, int) or isinstance(c, bool) or not 0 <= c < width for c in cols
            ):
                errs.append(
                    _err("param.range", "/params/columns", "columns must be inside the range")
                )
        if errs or ctx is None:
            return errs
        # Data-dependent check (review C2.1): never silently turn formulas into values.
        if any(c is not None and c.f for row in ctx.read_range(rng) for c in row):
            errs.append(_err("range_has_formulas", "/target/range", "the range contains formulas"))
        return errs

    # -------------------------------------------------------------- compute ----
    def _compute(
        self, op: Operation, ctx: ExecContext
    ) -> tuple[Range, list[list[CellValue | None]], int, list[Warning_]]:
        errs = self.validate(op, ctx)
        if errs:
            raise DomainError("validation_failed", details=[_detail(e) for e in errs])
        rng = _range_of(op)
        assert rng is not None  # noqa: S101 - validate() guarantees it
        grid = ctx.read_range(rng)
        has_header = bool(op.params.get("has_header", True)) and op.type != "find_replace"
        head, body = (grid[:1], grid[1:]) if has_header else ([], grid)
        warnings: list[Warning_] = []
        if op.type == "sort":
            for item in reversed(op.params["columns"]):
                col, desc = item["column"], bool(item.get("descending", False))
                body = _sorted_by(body, col, desc)
        elif op.type == "find_replace":
            body, n = _find_replace(body, op.params)
            warnings.append(
                Warning_(code="replaced", severity="info", message=f"{n} cells changed")
            )
        else:  # remove_duplicates
            cols = op.params.get("columns") or list(range(rng.c1 - rng.c0 + 1))
            seen: set[tuple[Any, ...]] = set()
            kept = []
            for row in body:
                key = tuple(_raw(row[c]) for c in cols)
                if key not in seen:
                    seen.add(key)
                    kept.append(row)
            warnings.append(
                Warning_(
                    code="removed", severity="info", message=f"{len(body) - len(kept)} rows removed"
                )
            )
            body = kept
        out = [[_val(c) for c in row] for row in head + body]
        return rng, out, len(body), warnings

    def preview(self, op: Operation, ctx: ExecContext, limit: int) -> PreviewResult:
        _, rows, total, warnings = self._compute(op, ctx)
        limit = max(1, min(limit, PREVIEW_MAX))
        shown = [[_raw_value(v) for v in r] for r in rows[:limit]]
        width = max((len(r) for r in shown), default=0)
        return PreviewResult(
            columns=[str(i) for i in range(width)], rows=shown, total_rows=total, warnings=warnings
        )

    def apply(self, op: Operation, ctx: ExecContext) -> OperationResult:
        rng, rows, _, warnings = self._compute(op, ctx)
        delta = ctx.write_range(rng, rows)
        n = sum(1 for _ in _changed(delta))
        return OperationResult(
            status="ok", affected=Affected(cells=n, rows=len(rows)), delta=delta, warnings=warnings
        )

    def run_pipeline(self, p: Pipeline, target: Target, ctx: ExecContext) -> list[OperationResult]:
        results: list[OperationResult] = []
        for step in p.steps:  # one write and one delta per step (review Q4)
            op = Operation(
                type=step.type,
                schema_version=step.schema_version,
                target=target,
                params=step.params,
            )
            results.append(self.apply(op, ctx))
        return results

    # ------------------------------------------------- charts / tools / etc ----
    def chart_data(self, spec: ChartSpec, ctx: ExecContext) -> ChartData:
        raise DomainError("bad_request", "Charts need the real dataops package (stub).")

    def validate_tool(
        self, tool: Tool, target: Target, ctx: ExecContext | None = None
    ) -> list[ValidationError]:
        errs: list[ValidationError] = []
        for i, step in enumerate(tool.pipeline.steps):
            if step.type not in _BY_TYPE:
                errs.append(_err("operation.unknown", f"/pipeline/steps/{i}/type", step.type))
        return errs

    def bind_tool(self, tool: Tool, inputs: dict[str, Any]) -> Pipeline:
        def sub(x: Any) -> Any:
            if isinstance(x, dict):
                if set(x) == {"$input"}:
                    name = x["$input"]
                    if name not in inputs:
                        raise DomainError("validation_failed", f"missing input {name!r}")
                    return inputs[name]
                return {k: sub(v) for k, v in x.items()}
            if isinstance(x, list):
                return [sub(v) for v in x]
            return x

        steps = [s.model_copy(update={"params": sub(s.params)}) for s in tool.pipeline.steps]
        return tool.pipeline.model_copy(update={"steps": steps})

    # (TableStore is implemented by StubTableStore below)


def _detail(e: ValidationError) -> Any:
    from gridora_contracts.models import ErrorDetail

    return ErrorDetail(code=e.code, path=e.path, message=e.message, hint=e.hint)


def _raw_value(v: CellValue | None) -> Any:
    return _raw(Cell(r=0, c=0, v=v)) if v is not None else None


def _changed(delta: Delta) -> list[int]:
    before = getattr(delta, "before", [])
    after = getattr(delta, "after", [])
    old = {(c.r, c.c): c.v for c in before}
    return [1 for c in after if old.get((c.r, c.c)) != c.v]


def _find_replace(body: list[list[Cell | None]], p: dict[str, Any]):  # type: ignore[no-untyped-def]
    find, repl = p["find"], p.get("replace", "")
    case, whole = bool(p.get("match_case", False)), bool(p.get("whole_cell", False))
    n = 0
    out = []
    for row in body:
        new_row = []
        for c in row:
            if c is not None and isinstance(c.v, StrValue):
                s = c.v.s
                hay, needle = (s, find) if case else (s.casefold(), find.casefold())
                if whole:
                    hit = hay == needle
                    new = repl if hit else s
                else:
                    hit = needle in hay
                    new = _replace_ci(s, find, repl, case) if hit else s
                if hit and new != s:
                    n += 1
                    c = c.model_copy(update={"v": StrValue(s=new)})
            new_row.append(c)
        out.append(new_row)
    return out, n


def _replace_ci(s: str, find: str, repl: str, case: bool) -> str:
    if case:
        return s.replace(find, repl)
    import re

    return re.sub(re.escape(find), lambda _m: repl, s, flags=re.IGNORECASE)


class StubTableStore:
    """Data Tables are not available with the stub; every call says so explicitly."""

    def _no(self) -> DomainError:
        return DomainError("bad_request", "Data Tables need the real dataops package (stub).")

    def create_from_rows(
        self, ctx: ExecContext, name: str, columns: list[Any], rows: list[list[Any]]
    ) -> DataTable:
        raise self._no()

    def read_page(
        self,
        table_id: str,
        offset: int,
        limit: int,
        sort: str | None = None,
        version: int | None = None,
    ) -> list[list[Any]]:
        raise self._no()

    def sheet_range_to_table(
        self,
        ctx: ExecContext,
        rng: Range,
        header_row: bool,
        dtype_overrides: dict[str, str] | None = None,
        preview: bool = False,
    ) -> Any:
        raise self._no()

    def table_to_cells(
        self, table_id: str, ctx: ExecContext, anchor: Range, version: int | None = None
    ) -> Delta:
        raise self._no()

    def restore_version(self, table_id: str, version: int) -> DataTable:
        raise self._no()


def create_executor(config: dict[str, Any] | None = None) -> StubExecutor:
    return StubExecutor()


def create_table_store(path_for: Any) -> StubTableStore:
    return StubTableStore()
