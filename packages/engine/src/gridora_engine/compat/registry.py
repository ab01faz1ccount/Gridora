"""Compatibility feature registry (PLAN.md §6).

Honesty gate: an entry with tier "supported" or "partial" must list fixtures (or "generated"
for fixtures built inside the tests) and at least one test; tests/unit/test_registry.py checks
that those tests exist. Tier -> contract mapping: supported->supported, partial->partial,
preserved->unsupported(preserved=True), unsupported->unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal["supported", "partial", "preserved", "unsupported"]


@dataclass(frozen=True)
class Feature:
    code: str
    tier: Tier
    handling: str
    message: str  # may contain {count}
    tests: tuple[str, ...] = ()
    fixtures: tuple[str, ...] = ("generated",)
    editable: bool = True


_FEATURES = (
    Feature(
        "csv.encoding_guessed", "partial", "decoded with a guessed encoding",
        "The text encoding was guessed ({count} file); check that text looks right.",
        tests=("test_windows1256_detected_and_reported", "test_latin_fallback_is_reported"),
    ),
    Feature(
        "csv.delimiter_detected", "partial", "delimiter chosen automatically",
        "The delimiter was detected automatically.",
        tests=("test_delimiter_detection",),
    ),
    Feature(
        "csv.persian_digits_normalized", "partial", "Persian/Arabic-Indic digits converted",
        "{count} numeric fields written in Persian or Arabic-Indic digits were converted to numbers.",
        tests=("test_persian_digits_become_numbers",),
    ),
    Feature(
        "csv.numeric_like_kept_as_text", "partial", "kept as text to avoid data loss",
        "{count} number-like fields (leading zero, leading +, or more than 15 digits) "
        "were kept as text.",
        tests=("test_identifiers_stay_text",),
    ),
    Feature(
        "csv.formula_text_neutralized", "partial", "prefixed with an apostrophe on export",
        "{count} text cells starting with = + - @ were prefixed with ' to prevent formula "
        "injection when the CSV is opened in a spreadsheet.",
        tests=("test_export_neutralizes_formula_text",),
    ),
)
REGISTRY: dict[str, Feature] = {f.code: f for f in _FEATURES}
