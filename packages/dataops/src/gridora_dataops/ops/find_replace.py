"""find_replace: literal text search/replace in text columns (no regex from users: no ReDoS, no surprises)."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from ..errors import DataOpsError, pointer
from ..ops_common import text_columns
from ..persian.chars import ARABIC_INDIC_DIGITS, DIACRITICS, PERSIAN_DIGITS, TATWEEL, ZWNJ
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv, column_field  # noqa: F401

_VARIANT_CLASS: dict[str, str] = {"ی": "یيى", "ي": "یيى", "ى": "یيى", "ک": "کك", "ك": "کك"}
for _d in range(10):
    _cls = f"{_d}{PERSIAN_DIGITS[_d]}{ARABIC_INDIC_DIGITS[_d]}"
    for _c in _cls:
        _VARIANT_CLASS[_c] = _cls
_IGNORABLE = TATWEEL + ZWNJ + DIACRITICS


def _esc(ch: str) -> str:
    return ch if ch.isalnum() else f"\\x{{{ord(ch):X}}}"


def needle_regex(needle: str, ignore_variants: bool) -> str:
    """Regex that matches `needle` literally; with `ignore_variants` also Arabic/Persian letter and digit variants,
    and tolerates tatweel/ZWNJ/diacritics between characters. The surrounding text is never changed."""
    parts = []
    for ch in needle:
        cls = _VARIANT_CLASS.get(ch) if ignore_variants else None
        parts.append(f"[{cls}]" if cls else _esc(ch))
    return (f"[{_IGNORABLE}]*" if ignore_variants else "").join(parts)


class FindReplaceParams(ParamsModel):
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
