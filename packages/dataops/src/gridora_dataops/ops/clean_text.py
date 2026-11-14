"""clean_text: whitespace, case and Persian/Arabic normalisation. Every Persian option is explicit and off by default."""
from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from ..ops_common import text_columns
from ..persian.chars import (
    ARABIC_INDIC_DIGITS,
    DIACRITICS,
    PERSIAN_DIGITS,
    TATWEEL,
    VARIANT_LETTERS,
    ZWNJ,
)
from ..spec import OperationSpec, OpOutput, ParamsModel, PlanEnv

_LATIN = "0123456789"
_DIGIT_TARGET = {"to_latin": _LATIN, "to_persian": PERSIAN_DIGITS, "to_arabic_indic": ARABIC_INDIC_DIGITS}


class CleanTextParams(ParamsModel):
    has_header: bool = Field(True, json_schema_extra={"x-gridora-order": 0})
    columns: list[str] = Field(default_factory=list, description="d", json_schema_extra={
        "x-gridora-column": True, "x-gridora-column-types": ["text"], "x-gridora-widget": "column-list",
        "x-gridora-order": 1})
    trim: bool = True
    collapse_spaces: bool = True
    nbsp_to_space: bool = True
    case: Literal["none", "upper", "lower", "title"] = "none"
    arabic_letters_to_persian: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})
    digits: Literal["none", "to_latin", "to_persian", "to_arabic_indic"] = Field(
        "none", json_schema_extra={"x-gridora-persian-option": True})
    remove_tatweel: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})
    zwnj: Literal["keep", "remove", "to_space"] = Field("keep", json_schema_extra={"x-gridora-persian-option": True})
    remove_diacritics: bool = Field(False, json_schema_extra={"x-gridora-persian-option": True})


def _replace(e: pl.Expr, mapping: dict[str, str]) -> pl.Expr:
    return e.str.replace_many(list(mapping), list(mapping.values()))


class CleanTextOp(OperationSpec):
    type = "clean_text"
    category = "clean"
    destructive = True
    Params = CleanTextParams

    def _clean(self, e: pl.Expr, p: CleanTextParams) -> pl.Expr:
        if p.nbsp_to_space:
            e = e.str.replace_all(r"[\u00a0\u202f]", " ")
        if p.zwnj == "remove":
            e = e.str.replace_all(ZWNJ, "", literal=True)
        elif p.zwnj == "to_space":
            e = e.str.replace_all(ZWNJ, " ", literal=True)
        if p.remove_tatweel:
            e = e.str.replace_all(TATWEEL, "", literal=True)
        if p.remove_diacritics:
            e = _replace(e, {ch: "" for ch in DIACRITICS})
        if p.arabic_letters_to_persian:
            e = _replace(e, VARIANT_LETTERS)
        if p.digits != "none":
            target = _DIGIT_TARGET[p.digits]
            mapping = {}
            for i in range(10):
                for src in (_LATIN[i], PERSIAN_DIGITS[i], ARABIC_INDIC_DIGITS[i]):
                    if src != target[i]:
                        mapping[src] = target[i]
            e = _replace(e, mapping)
        if p.collapse_spaces:
            e = e.str.replace_all(r"\s+", " ")
        if p.trim:
            e = e.str.strip_chars()
        if p.case == "upper":
            e = e.str.to_uppercase()
        elif p.case == "lower":
            e = e.str.to_lowercase()
        elif p.case == "title":
            e = e.str.to_titlecase()
        return e

    def plan(self, frame: pl.DataFrame, params: ParamsModel, env: PlanEnv) -> OpOutput:
        assert isinstance(params, CleanTextParams)
        cols = text_columns(frame, params.columns)
        return OpOutput(frame.with_columns([self._clean(pl.col(c), params) for c in cols]))
