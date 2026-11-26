"""Persian/Arabic character handling shared by sort, dedupe, find/replace, filter, join, group by and clean_text.

Everything is vectorised (Polars `str.replace_many`); no Python loops over rows. All rules are explicit
and documented here; nothing is applied to user data unless an operation option asks for it.
"""
from __future__ import annotations

import polars as pl
from gridora_contracts.persian import FOLD

# Persian alphabetical order (آ sorts directly before ا).
PERSIAN_ORDER = "آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"

ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"   # U+0660..U+0669
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"        # U+06F0..U+06F9
TATWEEL = "ـ"                          # U+0640
ZWNJ = "‌"                             # U+200C
DIACRITICS = "".join(chr(c) for c in range(0x064B, 0x0660)) + "ٰ"  # harakat + dagger alif

# Letters that are variants of a Persian letter (typed with an Arabic keyboard layout).
VARIANT_LETTERS = {"ي": "ی", "ى": "ی", "ك": "ک"}

_PUA = 0xE000  # private-use band: mapped characters sort after unmapped ones (punctuation, symbols, ...)


def _collation_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for d in range(10):
        table[str(d)] = chr(_PUA + d)
    for d, ch in enumerate(PERSIAN_DIGITS):
        table[ch] = chr(_PUA + d)
    for d, ch in enumerate(ARABIC_INDIC_DIGITS):
        table[ch] = chr(_PUA + d)
    for i in range(26):  # Latin sorts before Persian; case-insensitive at this level
        table[chr(ord("a") + i)] = chr(_PUA + 0x100 + i)
        table[chr(ord("A") + i)] = chr(_PUA + 0x100 + i)
    code = {ch: _PUA + 0x200 + 2 * i for i, ch in enumerate(PERSIAN_ORDER)}
    for ch, c in code.items():
        table[ch] = chr(c)
    folds = {"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا", "ؤ": "و"}
    for src, dst in folds.items():
        table[src] = chr(code[dst])
    table["ء"] = chr(code["ا"] + 1)  # hamza: just after alef
    for ch in TATWEEL + ZWNJ + DIACRITICS:  # ignorable at the primary level
        table[ch] = ""
    return table


_COLLATION = _collation_table()

def collation_key(expr: pl.Expr) -> pl.Expr:
    """Order-preserving sort key for Persian-aware ordering.

    Order: punctuation/space/symbols < digits (Latin, Persian and Arabic-Indic equal) < Latin letters
    (case-insensitive) < Persian letters in dictionary order. ي/ى/ئ -> ی, ك -> ک, أ/إ -> ا, ؤ -> و, ة/ۀ -> ه;
    tatweel, ZWNJ and diacritics are ignored. Ties keep their original order (stable sort).
    Limitations: no natural-number ordering, no Latin lowercase-before-uppercase tie-break.
    """
    return expr.str.replace_many(list(_COLLATION), list(_COLLATION.values()))


def variant_fold(expr: pl.Expr) -> pl.Expr:
    """Comparison form of text, vectorised: the same rules as `gridora_contracts.persian.fold_text`
    (the one definition shared with the engine's Find): Arabic letters, every alef, hamza carriers,
    all digit scripts, nbsp; tatweel, ZWNJ, diacritics and a lone hamza are dropped; NFKC first."""
    return expr.str.normalize("NFKC").str.replace_many(list(FOLD), list(FOLD.values()))
