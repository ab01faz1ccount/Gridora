"""join: combine the target with Operation.extra_targets[0] on key columns. Always creates a new table."""
from __future__ import annotations

from typing import Literal

import polars as pl
from gridora_contracts.models import Warning_
from pydantic import Field

from ..errors import DataOpsError, pointer, verr
from ..persian.chars import variant_fold
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv

MAX_MATCHED_ROWS = 5_000_000


class JoinParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    how: Literal["inner", "left", "right", "full"] = "inner"
    left_on: list[str] = Field(min_length=1, max_length=10, json_schema_extra={
        "x-gridora-column": True, "x-gridora-widget": "column-list", "x-gridora-order": 1})
    right_on: list[str] = Field(min_length=1, max_length=10, json_schema_extra={
        "x-gridora-column": True, "x-gridora-column-of": "extra_targets/0", "x-gridora-widget": "column-list",
        "x-gridora-order": 2})
    suffix: str = Field("_right", min_length=1, max_length=50)
    # text keys: "Tehran " and "tehran" are the same city to a person; both default to the strict behaviour
    trim: bool = False
    case_sensitive: bool = True
    ignore_variants: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})


def _family(dtype: pl.DataType) -> str:
    if dtype.is_numeric():
        return "number"
    if dtype == pl.String:
        return "text"
    if dtype == pl.Boolean:
        return "bool"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    return str(dtype)


def _suffix_clash(left: list[str], right: list[str], suffix: str) -> str | None:
    """The first result column name that would exist twice once right-hand duplicates get the suffix."""
    seen = set(left)
    for c in right:
        name = c + suffix if c in seen else c
        if name in seen:
            return name
        seen.add(name)
    return None


class JoinOp(OperationSpec):
    type = "join"
    category = "combine"
    destructive = False
    creates_table = True
    rewrites_cells = False  # reads the range, never changes it: formulas are fine (their values are used)
    extra_inputs = 1
    Params = JoinParams

    def validate_static(self, params: ParamsModel):  # type: ignore[no-untyped-def]
        assert isinstance(params, JoinParams)
        if len(params.left_on) != len(params.right_on):
            return [verr("invalid_param", pointer("params", "right_on"), "left_on and right_on need the same number of keys")]
        return []

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, JoinParams)
        right = env.extra_frames[0]
        lk, rk = [], []
        warns: list[Warning_] = []
        for i, (a, b) in enumerate(zip(params.left_on, params.right_on, strict=True)):
            fa, fb = _family(frame.schema[a]), _family(right.schema[b])
            if fa != fb:
                raise DataOpsError("type_mismatch", f"key '{a}' ({fa}) cannot be matched with '{b}' ({fb})",
                                   path=pointer("params", "right_on", i))
            ex_l, ex_r = pl.col(a), pl.col(b)
            if fa == "number":
                if frame.schema[a].is_integer() and right.schema[b].is_integer():
                    ex_l, ex_r = ex_l.cast(pl.Int64), ex_r.cast(pl.Int64)  # exact: floats would merge 2^53+1 and 2^53
                else:
                    ex_l, ex_r = ex_l.cast(pl.Float64), ex_r.cast(pl.Float64)
                    for df_, name in ((frame, a), (right, b)):
                        biggest = df_[name].abs().max() if df_.schema[name].is_integer() else None
                        if isinstance(biggest, int) and biggest > 2**53:
                            warns.append(Warning_(code="join_key_precision", severity="warn", location=name,
                                                  message=f"'{name}' holds integers beyond 2^53 that are compared with "
                                                          "decimals: nearby values can match each other"))
            elif fa == "text":
                if params.trim:
                    ex_l, ex_r = ex_l.str.strip_chars(), ex_r.str.strip_chars()
                if params.ignore_variants:
                    ex_l, ex_r = variant_fold(ex_l), variant_fold(ex_r)
                if not params.case_sensitive:
                    ex_l, ex_r = ex_l.str.to_lowercase(), ex_r.str.to_lowercase()
            lk.append(ex_l.alias(f"__jk{i}"))
            rk.append(ex_r.alias(f"__jk{i}"))
        names = [f"__jk{i}" for i in range(len(lk))]
        lcount = frame.select(lk).group_by(names).len().rename({"len": "l"})
        rcount = right.select(rk).group_by(names).len().rename({"len": "r"})
        pairs = lcount.join(rcount, on=names, how="inner").select((pl.col("l") * pl.col("r")).sum()).item() or 0
        if pairs > MAX_MATCHED_ROWS:
            raise DataOpsError("result_too_large", f"the join would produce {pairs} matching rows "
                               f"(limit {MAX_MATCHED_ROWS})", path=pointer("params", "left_on"))
        left_w = frame.with_columns(lk)
        keep_right_keys = [pl.col(b).alias(f"__rk{i}") for i, b in enumerate(params.right_on)]
        right_w = right.with_columns(rk + keep_right_keys).drop(list(dict.fromkeys(params.right_on)))
        order: Literal["right_left", "left_right"] = "right_left" if params.how == "right" else "left_right"
        clash = _suffix_clash(frame.columns, [c for c in right_w.columns if c not in names and not c.startswith("__rk")],
                              params.suffix)
        if clash:
            raise DataOpsError("invalid_param", f"the column name '{clash}' would appear twice in the result",
                               path=pointer("params", "suffix"), hint="choose another suffix or rename a column first")
        out = left_w.join(right_w, on=names, how=params.how, suffix=params.suffix, coalesce=True,
                          maintain_order=order)
        if params.how in ("right", "full"):  # rows that exist only on the right keep their key values
            out = out.with_columns([
                pl.coalesce(pl.col(a), pl.col(f"__rk{i}").cast(frame.schema[a], strict=False)).alias(a)
                for i, a in enumerate(params.left_on)])
        return OpOutput(out.drop(names + [f"__rk{i}" for i in range(len(names))]), warns)
