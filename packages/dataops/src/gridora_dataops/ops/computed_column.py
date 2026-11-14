"""computed_column: a new column from a structured expression tree (never a string, never eval; ADR-007).

Allow-listed functions only, a type check before anything runs, limits on depth and size. Errors point at the node
(`/params/expr/args/1`). Division by zero gives an empty cell and a warning, not an exception.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, Optional, Union

import polars as pl
from gridora_contracts.models import Warning_
from pydantic import BaseModel, ConfigDict, Field

from ..errors import DataOpsError, pointer, verr
from ..ops_common import unique_name
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field

MAX_DEPTH = 20
MAX_NODES = 200

Fn = Literal[
    "add", "sub", "mul", "div", "mod", "neg", "abs", "floor", "ceil", "round", "min2", "max2",
    "concat", "upper", "lower", "trim", "len", "left", "right", "substring", "replace",
    "eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not", "if", "is_null", "coalesce",
    "year", "month", "day",
]


class Lit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["lit"] = "lit"
    value: Optional[Union[bool, float, str]] = None


class Col(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["col"] = "col"
    name: str = column_field()


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["call"] = "call"
    fn: Fn
    args: list[Annotated[Union[Lit, Col, Call], Field(discriminator="kind")]] = Field(default_factory=list, max_length=10)


Call.model_rebuild()
Node = Union[Lit, Col, Call]


class ComputedParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    name: str = Field(min_length=1, max_length=200, json_schema_extra={"x-gridora-order": 1})
    expr: Annotated[Union[Lit, Col, Call], Field(discriminator="kind")] = Field(
        json_schema_extra={"x-gridora-widget": "expression-builder", "x-gridora-order": 2})


# --------------------------------------------------------------------------- typing
Ty = Literal["num", "text", "bool", "date", "datetime", "null"]


def _ty(dtype: pl.DataType) -> Ty:
    if dtype.is_numeric():
        return "num"
    if dtype == pl.Boolean:
        return "bool"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    return "text"


@dataclass
class _Fn:
    lo: int
    hi: int
    check: Callable[[list[Ty]], Optional[Ty]]  # result type or None when the argument types do not fit
    build: Callable[[list[pl.Expr]], pl.Expr]


def _unify(types: list[Ty]) -> Optional[Ty]:
    real = {t for t in types if t != "null"}
    return None if len(real) > 1 else (next(iter(real)) if real else "null")


def _all(t: Ty, result: Ty) -> Callable[[list[Ty]], Optional[Ty]]:
    return lambda a: result if all(x in (t, "null") for x in a) else None


def _same(result: Ty) -> Callable[[list[Ty]], Optional[Ty]]:
    return lambda a: result if _unify(a) is not None else None


def _sig(*want: Ty, result: Ty) -> Callable[[list[Ty]], Optional[Ty]]:
    return lambda a: result if all(x in (w, "null") for x, w in zip(a, want, strict=False)) else None


def _safe_div(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return pl.when(b == 0).then(None).otherwise(a / b)


def _safe_mod(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return pl.when(b == 0).then(None).otherwise(a % b)


def _text(e: pl.Expr, t: Ty) -> pl.Expr:
    if t == "num":
        f = e.cast(pl.Float64)
        whole = f.is_finite() & (f == f.floor()) & (f.abs() < 1e15)
        return pl.when(whole).then(f.cast(pl.Int64).cast(pl.String)).otherwise(e.cast(pl.String))
    if t == "bool":
        return pl.when(e).then(pl.lit("true")).otherwise(pl.lit("false"))
    if t == "date":
        return e.dt.to_string("%Y-%m-%d")
    if t == "datetime":
        return e.dt.to_string("%Y-%m-%d %H:%M:%S")
    return e


FUNCS: dict[str, _Fn] = {
    "add": _Fn(2, 2, _all("num", "num"), lambda a: a[0] + a[1]),
    "sub": _Fn(2, 2, _all("num", "num"), lambda a: a[0] - a[1]),
    "mul": _Fn(2, 2, _all("num", "num"), lambda a: a[0] * a[1]),
    "div": _Fn(2, 2, _all("num", "num"), lambda a: _safe_div(a[0], a[1])),
    "mod": _Fn(2, 2, _all("num", "num"), lambda a: _safe_mod(a[0], a[1])),
    "neg": _Fn(1, 1, _all("num", "num"), lambda a: -a[0]),
    "abs": _Fn(1, 1, _all("num", "num"), lambda a: a[0].abs()),
    "floor": _Fn(1, 1, _all("num", "num"), lambda a: a[0].floor()),
    "ceil": _Fn(1, 1, _all("num", "num"), lambda a: a[0].ceil()),
    "round": _Fn(1, 1, _all("num", "num"), lambda a: a[0].round(0)),
    "min2": _Fn(2, 2, _all("num", "num"), lambda a: pl.min_horizontal(a)),
    "max2": _Fn(2, 2, _all("num", "num"), lambda a: pl.max_horizontal(a)),
    "upper": _Fn(1, 1, _all("text", "text"), lambda a: a[0].str.to_uppercase()),
    "lower": _Fn(1, 1, _all("text", "text"), lambda a: a[0].str.to_lowercase()),
    "trim": _Fn(1, 1, _all("text", "text"), lambda a: a[0].str.strip_chars()),
    "len": _Fn(1, 1, _sig("text", result="num"), lambda a: a[0].str.len_chars()),
    "left": _Fn(2, 2, _sig("text", "num", result="text"), lambda a: a[0].str.slice(0, a[1].cast(pl.Int64))),
    "right": _Fn(2, 2, _sig("text", "num", result="text"),
                 lambda a: a[0].str.slice((a[0].str.len_chars().cast(pl.Int64) - a[1].cast(pl.Int64)).clip(lower_bound=0))),
    "substring": _Fn(3, 3, _sig("text", "num", "num", result="text"),
                     lambda a: a[0].str.slice((a[1].cast(pl.Int64) - 1).clip(lower_bound=0), a[2].cast(pl.Int64))),
    "replace": _Fn(3, 3, _sig("text", "text", "text", result="text"),
                   lambda a: a[0].str.replace_all(a[1], a[2], literal=True)),
    "eq": _Fn(2, 2, lambda a: "bool" if _unify(a) is not None else None, lambda a: a[0] == a[1]),
    "ne": _Fn(2, 2, lambda a: "bool" if _unify(a) is not None else None, lambda a: a[0] != a[1]),
    "lt": _Fn(2, 2, lambda a: "bool" if _unify(a) not in (None, "bool") else None, lambda a: a[0] < a[1]),
    "le": _Fn(2, 2, lambda a: "bool" if _unify(a) not in (None, "bool") else None, lambda a: a[0] <= a[1]),
    "gt": _Fn(2, 2, lambda a: "bool" if _unify(a) not in (None, "bool") else None, lambda a: a[0] > a[1]),
    "ge": _Fn(2, 2, lambda a: "bool" if _unify(a) not in (None, "bool") else None, lambda a: a[0] >= a[1]),
    "and": _Fn(2, 10, _all("bool", "bool"), lambda a: pl.all_horizontal(a)),
    "or": _Fn(2, 10, _all("bool", "bool"), lambda a: pl.any_horizontal(a)),
    "not": _Fn(1, 1, _all("bool", "bool"), lambda a: ~a[0]),
    "is_null": _Fn(1, 1, lambda a: "bool", lambda a: a[0].is_null()),
    "coalesce": _Fn(2, 10, lambda a: _unify(a), lambda a: pl.coalesce(a)),
}


class _Compiler:
    def __init__(self, schema: pl.Schema) -> None:
        self.schema = schema
        self.nodes = 0
        self.zero_checks: list[pl.Expr] = []

    def compile(self, n: Node, ptr: str, depth: int = 1) -> tuple[pl.Expr, Ty]:
        self.nodes += 1
        if depth > MAX_DEPTH or self.nodes > MAX_NODES:
            raise DataOpsError("invalid_param", f"expression is too large (depth {MAX_DEPTH}, {MAX_NODES} nodes max)", path=ptr)
        if isinstance(n, Lit):
            v = n.value
            if v is None:
                return pl.lit(None), "null"
            if isinstance(v, bool):
                return pl.lit(v), "bool"
            return (pl.lit(float(v)), "num") if isinstance(v, (int, float)) else (pl.lit(v), "text")
        if isinstance(n, Col):
            return pl.col(n.name), _ty(self.schema[n.name])
        compiled = [self.compile(a, f"{ptr}/args/{i}", depth + 1) for i, a in enumerate(n.args)]
        exprs, types = [c[0] for c in compiled], [c[1] for c in compiled]
        if n.fn == "if":
            if len(n.args) != 3 or types[0] not in ("bool", "null") or _unify(types[1:]) is None:
                raise DataOpsError("type_mismatch", "'if' needs a yes/no test and two values of one type", path=ptr)
            return pl.when(exprs[0]).then(exprs[1]).otherwise(exprs[2]), _unify(types[1:]) or "null"
        if n.fn == "concat":
            if len(n.args) < 2:
                raise DataOpsError("invalid_param", "'concat' needs at least 2 arguments", path=ptr + "/args")
            return pl.concat_str([_text(e, t) for e, t in zip(exprs, types, strict=True)], ignore_nulls=True), "text"
        if n.fn in ("year", "month", "day"):
            if len(n.args) != 1 or types[0] not in ("date", "datetime", "null"):
                raise DataOpsError("type_mismatch", f"'{n.fn}' needs one date", path=ptr)
            part = {"year": exprs[0].dt.year, "month": exprs[0].dt.month, "day": exprs[0].dt.day}[n.fn]
            return part().cast(pl.Float64), "num"
        f = FUNCS[n.fn]
        if not f.lo <= len(n.args) <= f.hi:
            raise DataOpsError("invalid_param", f"'{n.fn}' takes {f.lo}" + (f" to {f.hi}" if f.hi != f.lo else "")
                               + " argument(s)", path=ptr + "/args")
        result = f.check(types)
        if result is None:
            raise DataOpsError("type_mismatch", f"'{n.fn}' does not accept {', '.join(types)}", path=ptr)
        if n.fn in ("div", "mod"):
            self.zero_checks.append(((exprs[1] == 0) & exprs[0].is_not_null()).sum())
        return f.build(exprs), result


def _count(n: Node) -> int:
    return 1 + (sum(_count(a) for a in n.args) if isinstance(n, Call) else 0)


class ComputedColumnOp(OperationSpec):
    type = "computed_column"
    category = "calculate"
    destructive = False
    Params = ComputedParams

    def validate_static(self, params: ParamsModel):  # type: ignore[no-untyped-def]
        assert isinstance(params, ComputedParams)
        if _count(params.expr) > MAX_NODES:
            return [verr("invalid_param", pointer("params", "expr"), f"more than {MAX_NODES} nodes")]
        return []

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, ComputedParams)
        if params.name in frame.columns:
            raise DataOpsError("invalid_param", f"a column named '{params.name}' already exists",
                               path=pointer("params", "name"))
        comp = _Compiler(frame.schema)
        expr, ty = comp.compile(params.expr, pointer("params", "expr"))
        name = unique_name(params.name, set(frame.columns))
        out = frame.with_columns(expr.alias(name))
        warnings: list[Warning_] = []
        if comp.zero_checks:
            zeros = sum(int(x or 0) for x in frame.select(comp.zero_checks).row(0))
            if zeros:
                warnings.append(Warning_(code="division_by_zero", severity="warn", location=name,
                                         message=f"{zeros} division(s) by zero left empty cells"))
        _ = ty
        return OpOutput(out, warnings)
