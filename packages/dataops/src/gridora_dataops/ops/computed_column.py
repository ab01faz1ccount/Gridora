"""computed_column: a new column from a structured expression tree (never a string, never eval; ADR-007).

Allow-listed functions only, a type check before anything runs, limits on depth and size. Errors point at the node
(`/params/expr/args/1`). Division by zero gives an empty cell and a warning, not an exception.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union

import polars as pl
from gridora_contracts.models import Warning_
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..conversions import number_text
from ..errors import DataOpsError, pointer, verr
from ..ops_common import unique_name
from ..persian.chars import variant_fold
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, RewriteParams, column_field

MAX_DEPTH = 20
MAX_NODES = 200

Fn = Literal[
    "add", "sub", "mul", "div", "mod", "neg", "abs", "floor", "ceil", "round", "min2", "max2",
    "concat", "upper", "lower", "trim", "len", "left", "right", "substring", "replace",
    "eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not", "if", "is_null", "coalesce",
    "year", "month", "day",
    "to_number", "to_text", "fold", "contains", "starts_with", "ends_with", "switch", "between",
    "days_between", "add_days",
]
INT_LIMIT = 2**53  # a literal beyond this would silently lose digits as a float


# One row per function: (category, signature, result type). The expression builder reads this from the schema
# (`x-gridora-functions`), so a function added to `Fn` without a row here fails a test.
FN_META: dict[str, tuple[str, str, str]] = {
    "add": ("math", "add(number, number)", "num"), "sub": ("math", "sub(number, number)", "num"),
    "mul": ("math", "mul(number, number)", "num"), "div": ("math", "div(number, number)", "num"),
    "mod": ("math", "mod(number, number)", "num"), "neg": ("math", "neg(number)", "num"),
    "abs": ("math", "abs(number)", "num"), "floor": ("math", "floor(number)", "num"),
    "ceil": ("math", "ceil(number)", "num"), "round": ("math", "round(number, digits?)", "num"),
    "min2": ("math", "min2(number, number)", "num"), "max2": ("math", "max2(number, number)", "num"),
    "between": ("math", "between(value, low, high)", "bool"),
    "concat": ("text", "concat(any, any, ...)", "text"), "upper": ("text", "upper(text)", "text"),
    "lower": ("text", "lower(text)", "text"), "trim": ("text", "trim(text)", "text"),
    "len": ("text", "len(text)", "num"), "left": ("text", "left(text, count)", "text"),
    "right": ("text", "right(text, count)", "text"),
    "substring": ("text", "substring(text, start, count)", "text"),
    "replace": ("text", "replace(text, find, with)", "text"), "fold": ("text", "fold(text)", "text"),
    "contains": ("text", "contains(text, part)", "bool"), "starts_with": ("text", "starts_with(text, part)", "bool"),
    "ends_with": ("text", "ends_with(text, part)", "bool"),
    "eq": ("logic", "eq(value, value)", "bool"), "ne": ("logic", "ne(value, value)", "bool"),
    "lt": ("logic", "lt(value, value)", "bool"), "le": ("logic", "le(value, value)", "bool"),
    "gt": ("logic", "gt(value, value)", "bool"), "ge": ("logic", "ge(value, value)", "bool"),
    "and": ("logic", "and(yes/no, yes/no, ...)", "bool"), "or": ("logic", "or(yes/no, yes/no, ...)", "bool"),
    "not": ("logic", "not(yes/no)", "bool"), "if": ("logic", "if(test, then, else)", "any"),
    "switch": ("logic", "switch(value, key, result, ..., default?)", "any"),
    "is_null": ("logic", "is_null(any)", "bool"), "coalesce": ("logic", "coalesce(any, any, ...)", "any"),
    "year": ("date", "year(date)", "num"), "month": ("date", "month(date)", "num"), "day": ("date", "day(date)", "num"),
    "days_between": ("date", "days_between(from, to)", "num"), "add_days": ("date", "add_days(date, days)", "date"),
    "to_number": ("convert", "to_number(text, decimal separator?)", "num"), "to_text": ("convert", "to_text(any)", "text"),
}


def function_catalog() -> list[Any]:
    return [{"fn": f, "category": c, "signature": sig, "returns": r} for f, (c, sig, r) in FN_META.items()]


class Lit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["lit"] = "lit"
    value: Optional[Union[bool, float, str]] = None

    @field_validator("value", mode="before")
    @classmethod
    def _no_silent_precision_loss(cls, v: object) -> object:
        if isinstance(v, int) and not isinstance(v, bool) and abs(v) > INT_LIMIT:
            raise ValueError(f"numbers beyond {INT_LIMIT} cannot be represented exactly: use a text column")
        return v


class Col(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["col"] = "col"
    name: str = column_field()


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["call"] = "call"
    fn: Fn
    args: list[Annotated[Union[Lit, Col, Call], Field(discriminator="kind")]] = Field(default_factory=list, max_length=21)  # switch: value + up to 9 pairs + default


Call.model_rebuild()
Node = Union[Lit, Col, Call]


class ComputedParams(RewriteParams):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    name: str = Field(min_length=1, max_length=200, json_schema_extra={"x-gridora-order": 1})
    expr: Annotated[Union[Lit, Col, Call], Field(discriminator="kind")] = Field(
        json_schema_extra={"x-gridora-widget": "expression-builder", "x-gridora-order": 2,
                           "x-gridora-functions": function_catalog()})


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


def _count_of(e: pl.Expr) -> pl.Expr:
    """A character count: negative means none (it used to crash the whole run)."""
    return e.cast(pl.Int64).clip(lower_bound=0)


def _both_known(args: list[pl.Expr], value: pl.Expr) -> pl.Expr:
    return pl.when(args[0].is_not_null() & args[1].is_not_null()).then(value)


def _round_digits(e: pl.Expr, digits: int) -> pl.Expr:
    """Half away from zero on the DECIMAL value the user sees: 1.005 is stored as 1.00499999999999989..., so the
    scaled number is first cleaned to 15 significant digits (1.005 -> 1.01, 2.675 -> 2.68, as a spreadsheet does)."""
    if digits == 0:
        return e.round(0, mode="half_away_from_zero")
    scale = 10.0**digits
    # the final clean-up matters: a division can land one ulp off (2675 / 1000 -> 2.6750000000000003)
    return ((e * scale).round_sig_figs(15).round(0, mode="half_away_from_zero") / scale).round_sig_figs(15)


def _safe_div(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return pl.when(b == 0).then(None).otherwise(a / b)


def _safe_mod(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return pl.when(b == 0).then(None).otherwise(a % b)


def _text(e: pl.Expr, t: Ty) -> pl.Expr:
    if t == "num":
        f = e.cast(pl.Float64)
        whole = f.is_finite() & (f == f.floor()) & (f.abs() < 1e15)
        # 0.1 + 0.2 shows as 0.3 (15 significant digits, as a spreadsheet does), not 0.30000000000000004
        # integers from 10^15 up (card numbers, long ids) are written in full: 15 significant digits would round them
        return (pl.when(whole).then(f.cast(pl.Int64).cast(pl.String))
                .when(f.abs() >= 1e15).then(e.cast(pl.String))
                .otherwise(f.round_sig_figs(15).cast(pl.String)))
    if t == "bool":
        return pl.when(e).then(pl.lit("true")).when(~e).then(pl.lit("false"))  # an empty cell stays empty, not "false"
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
    "round": _Fn(1, 2, _all("num", "num"), lambda a: a[0].round(0, mode="half_away_from_zero")),  # 2.5 -> 3, -2.5 -> -3
    # an empty cell in either argument gives an empty result, like add/sub/mul (use coalesce to pick a stand-in)
    "min2": _Fn(2, 2, _all("num", "num"), lambda a: _both_known(a, pl.min_horizontal(a))),
    "max2": _Fn(2, 2, _all("num", "num"), lambda a: _both_known(a, pl.max_horizontal(a))),
    "upper": _Fn(1, 1, _all("text", "text"), lambda a: a[0].str.to_uppercase()),
    "lower": _Fn(1, 1, _all("text", "text"), lambda a: a[0].str.to_lowercase()),
    "trim": _Fn(1, 1, _all("text", "text"), lambda a: a[0].str.strip_chars()),
    "len": _Fn(1, 1, _sig("text", result="num"), lambda a: a[0].str.len_chars()),
    "left": _Fn(2, 2, _sig("text", "num", result="text"), lambda a: a[0].str.slice(0, _count_of(a[1]))),
    "right": _Fn(2, 2, _sig("text", "num", result="text"),
                 lambda a: a[0].str.slice((a[0].str.len_chars().cast(pl.Int64) - _count_of(a[1])).clip(lower_bound=0))),
    "substring": _Fn(3, 3, _sig("text", "num", "num", result="text"),
                     lambda a: a[0].str.slice((a[1].cast(pl.Int64) - 1).clip(lower_bound=0), _count_of(a[2]))),
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
    "fold": _Fn(1, 1, _all("text", "text"), lambda a: variant_fold(a[0])),  # compare form: ي/ك, digits, ZWNJ ...
    "contains": _Fn(2, 2, _all("text", "bool"), lambda a: a[0].str.contains(a[1], literal=True)),
    "starts_with": _Fn(2, 2, _all("text", "bool"), lambda a: a[0].str.starts_with(a[1])),
    "ends_with": _Fn(2, 2, _all("text", "bool"), lambda a: a[0].str.ends_with(a[1])),
    "between": _Fn(3, 3, lambda a: "bool" if _unify(a) not in (None, "bool") else None,
                   lambda a: (a[0] >= a[1]) & (a[0] <= a[2])),
}


class _Compiler:
    def __init__(self, schema: pl.Schema) -> None:
        self.schema = schema
        self.nodes = 0
        self.zero_checks: list[pl.Expr] = []
        self.parse_checks: list[pl.Expr] = []  # to_number: texts that were not empty but are not numbers

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
        special = self._special(n, exprs, types, ptr)
        if special is not None:
            return special
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


    def _special(self, n: Call, exprs: list[pl.Expr], types: list[Ty], ptr: str) -> Optional[tuple[pl.Expr, Ty]]:
        """Functions whose shape (a literal option, a variable argument list) the table in FUNCS cannot express."""
        fn, k = n.fn, len(n.args)
        if fn == "round" and k == 2:
            d = n.args[1]
            if types[0] not in ("num", "null") or not (isinstance(d, Lit) and isinstance(d.value, (int, float))
                                                       and not isinstance(d.value, bool)
                                                       and float(d.value).is_integer() and 0 <= d.value <= 15):
                raise DataOpsError("type_mismatch", "'round' needs a number and, optionally, a literal digit count 0..15",
                                   path=ptr + "/args/1")
            return _round_digits(exprs[0], int(d.value)), "num"
        if fn == "to_number":
            sep = "."
            if k == 2:
                d = n.args[1]
                if not (isinstance(d, Lit) and d.value in (",", ".")):
                    raise DataOpsError("invalid_param", "the decimal separator of 'to_number' must be the literal \".\" or \",\"",
                                       path=ptr + "/args/1")
                sep = str(d.value)
            if k not in (1, 2) or types[0] not in ("text", "null"):
                raise DataOpsError("type_mismatch", "'to_number' needs text (digits of any script, thousands separators)", path=ptr)
            cleaned = number_text(exprs[0], sep)
            parsed = cleaned.cast(pl.Float64, strict=False)
            out = pl.when(parsed.is_finite()).then(parsed)
            self.parse_checks.append((cleaned.is_not_null() & out.is_null()).sum())
            return out, "num"
        if fn == "to_text":
            if k != 1:
                raise DataOpsError("invalid_param", "'to_text' takes 1 argument", path=ptr + "/args")
            return _text(exprs[0], types[0]), "text"
        if fn == "switch":
            if k < 3:
                raise DataOpsError("invalid_param", "'switch' needs a value, at least one key/result pair and an optional default",
                                   path=ptr + "/args")
            pairs, has_default = (k - 1) // 2, k % 2 == 0
            keys, results = types[1:1 + 2 * pairs:2], types[2:2 + 2 * pairs:2]
            if has_default:
                results = [*results, types[-1]]
            if _unify([types[0], *keys]) is None or _unify(results) is None:
                raise DataOpsError("type_mismatch", "'switch' keys must match the value's type and all results must share one type", path=ptr)
            chain: Any = pl.when(exprs[0] == exprs[1]).then(exprs[2])
            for i in range(1, pairs):
                chain = chain.when(exprs[0] == exprs[1 + 2 * i]).then(exprs[2 + 2 * i])
            return chain.otherwise(exprs[-1] if has_default else pl.lit(None)), _unify(results) or "null"
        if fn in ("days_between", "add_days"):
            when_types = ("date", "datetime", "null")
            if fn == "days_between":
                if k != 2 or any(t not in when_types for t in types):
                    raise DataOpsError("type_mismatch", "'days_between' needs two dates", path=ptr)
                a, b = (e.cast(pl.Datetime("us")) for e in exprs)
                return (b - a).dt.total_days().cast(pl.Float64), "num"
            if k != 2 or types[0] not in when_types or types[1] not in ("num", "null"):
                raise DataOpsError("type_mismatch", "'add_days' needs a date and a number of days", path=ptr)
            return exprs[0] + pl.duration(days=exprs[1].cast(pl.Int64)), types[0]
        return None


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
        if comp.parse_checks:
            bad = sum(int(x or 0) for x in frame.select(comp.parse_checks).row(0))
            if bad:
                warnings.append(Warning_(code="number_parse_failed", severity="warn", location=name,
                                         message=f"{bad} text value(s) are not numbers and left empty cells"))
        _ = ty
        return OpOutput(out, warnings)
