"""Discovery metadata for the operation catalog (UX_SPEC 3.1): task phrases, examples and a search over them.

Everything lives in the i18n catalog so Persian wording can change without code:
  `ops.<type>.keywords`  Persian task phrases a newcomer would type, separated by the Persian comma `،`;
  `ops.<type>.example`   a JSON string: {params, before:{columns,rows}, after:{columns,rows}, extra?, types?, caption}
                         (a test runs every example through the real operation, so an example can never lie).
English falls back to Persian per key, as for every catalog entry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import polars as pl

from .catalog import catalog
from .persian.chars import variant_fold

SEPARATOR = "،"


def keywords(type_: str, locale: str = "fa") -> list[str]:
    raw = catalog(locale).get(f"ops.{type_}.keywords", "")
    return [k.strip() for k in raw.split(SEPARATOR) if k.strip()]


def example(type_: str, locale: str = "fa") -> Optional[dict[str, Any]]:
    raw = catalog(locale).get(f"ops.{type_}.example")
    return json.loads(raw) if raw else None


def normalize(text: str) -> str:
    """Comparison form: Arabic letter variants and digit scripts folded, ZWNJ/tatweel/diacritics dropped, lower case,
    single spaces. So `كتاب`, `کتاب` and `کتـاب` are the same query."""
    folded = pl.DataFrame({"t": [text]}).select(variant_fold(pl.col("t")))["t"][0]
    return " ".join(folded.lower().split())


@dataclass(frozen=True)
class SearchHit:
    type: str
    score: int
    matched: str  # the phrase (or `label`/`description`) that matched, for highlighting


def search_operations(query: str, types: list[str], locale: str = "fa", limit: int = 8) -> list[SearchHit]:
    """Rank operations for a task phrase. `types` are the operation ids to search (e.g. from `describe_all()`).

    Scores: whole phrase 100, phrase starts with the query 80, phrase contains it 60, every word of the query occurs
    in some phrase/label/description 40. Ties are ordered by operation id so results are deterministic."""
    q = normalize(query)
    if not q:
        return []
    words = q.split()
    cat = catalog(locale)
    hits: list[SearchHit] = []
    for t in types:
        phrases = [(k, normalize(k)) for k in keywords(t, locale)]
        phrases += [(label, normalize(label)) for label in [cat.get(f"ops.{t}.label", "")] if label]
        best, matched = 0, ""
        for original, p in phrases:
            score = 100 if p == q else 80 if p.startswith(q) else 60 if q in p else 0
            if score > best:
                best, matched = score, original
        if not best:
            haystack = " ".join([p for _, p in phrases] + [normalize(cat.get(f"ops.{t}.description", ""))])
            if all(w in haystack for w in words):
                best, matched = 40, cat.get(f"ops.{t}.label", t)
        if best:
            hits.append(SearchHit(t, best, matched))
    return sorted(hits, key=lambda h: (-h.score, h.type))[:limit]
