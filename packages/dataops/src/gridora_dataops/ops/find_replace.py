"""find_replace: literal text search/replace in text columns (no regex from users: no ReDoS, no surprises)."""
from __future__ import annotations

from typing import Literal

import polars as pl
from gridora_contracts.persian import FOLD, IGNORED, variants_of
from pydantic import Field

from ..errors import DataOpsError, pointer
from ..ops_common import text_columns
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, RewriteParams

_IGNORABLE = IGNORED  # tolerated between the characters of the needle
_CLASSES = {ch: variants_of(ch) for ch in {*FOLD, *FOLD.values()} - {""} if variants_of(ch) not in ("", ch)}


def _esc(ch: str) -> str:
    return ch if ch.isalnum() else f"\\x{{{ord(ch):X}}}"


def needle_regex(needle: str, ignore_variants: bool) -> str:
    """Regex that matches `needle` literally; with `ignore_variants` also Arabic/Persian letter, alef, hamza and
    digit variants, and tolerates tatweel/ZWNJ/diacritics/hamza between characters. The surrounding text is
    never changed."""
    parts = []
    for ch in needle:
        if ignore_variants and ch in IGNORED:
            continue  # ignorable characters are tolerated anyway: they need not be typed
        cls = _CLASSES.get(ch) if ignore_variants else None
        parts.append(f"[{''.join(_esc(c) for c in cls)}]" if cls else _esc(ch))
    if not parts:  # nothing but ignorable characters: match them literally rather than everything
        return "".join(_esc(ch) for ch in needle)
    return (f"[{_IGNORABLE}]*" if ignore_variants else "").join(parts)


class FindReplaceParams(RewriteParams):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    columns: list[str] = Field(default_factory=list, description="d", json_schema_extra={
        "x-gridora-column": True, "x-gridora-column-types": ["text"], "x-gridora-widget": "column-list",
        "x-gridora-order": 1})
    find: str = Field(min_length=1, max_length=1000)
    replace: str = Field("", max_length=1000)
    match: Literal["partial", "whole"] = "partial"
    case_sensitive: bool = False
    ignore_variants: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})


class FindReplaceOp(OperationSpec):
    type = "find_replace"
    category = "clean"
    destructive = True
    Params = FindReplaceParams

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, FindReplaceParams)
        if not params.find:
            raise DataOpsError("invalid_param", "find text is empty", path=pointer("params", "find"))
        pat = needle_regex(params.find, params.ignore_variants)
        pat = f"^(?:{pat})$" if params.match == "whole" else pat
        pat = ("(?s)" if params.match == "whole" else "") + ("" if params.case_sensitive else "(?i)") + pat
        repl = params.replace.replace("$", "$$")
        cols = text_columns(frame, params.columns)
        return OpOutput(frame.with_columns([pl.col(c).str.replace_all(pat, repl) for c in cols]))
