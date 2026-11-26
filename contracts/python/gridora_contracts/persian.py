"""Persian / Arabic text folding: ONE definition shared by the engine (Find) and dataops (filter, find &
replace, remove duplicates, join, group by).

`fold_text` makes text that LOOKS the same compare the same, whichever keyboard or source typed it. It is
for matching only: no operation writes the folded text back into a cell (clean_text is the explicit
rewrite). What is folded:

- Arabic letters to their Persian form: ي ى -> ی, ك -> ک, ھ -> ه, ة ۀ -> ه
- every alef: أ إ ٱ آ -> ا          (آ is folded too: people often type ا for آ)
- hamza carriers: ئ -> ی, ؤ -> و, and a lone ء is ignored
- digits of all scripts -> Latin 0-9
- ignored completely: tatweel, ZWNJ / ZWJ, direction marks, Arabic diacritics (fatha, kasra, shadda ...)
- non-breaking spaces -> a normal space
- NFKC first, so presentation forms (copied from PDFs) and decomposed آ become the ordinary letters
"""
from __future__ import annotations

import unicodedata

ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"  # U+0660..U+0669
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"  # U+06F0..U+06F9
TATWEEL = "ـ"  # U+0640
ZWNJ = "‌"  # U+200C
ZWJ = "‍"  # U+200D
MARKS = "\u200e\u200f"  # LRM, RLM
HAMZA = "ء"
# harakat, tanwin, shadda, sukun, dagger alef and the Quranic annotation signs
DIACRITICS = "".join(chr(c) for c in (*range(0x0610, 0x061B), *range(0x064B, 0x0660), 0x0670,
                                     *range(0x06D6, 0x06DD), *range(0x06DF, 0x06E9), *range(0x06EA, 0x06EE)))
IGNORED = TATWEEL + ZWNJ + ZWJ + MARKS + HAMZA + DIACRITICS

# source character -> what it compares as
LETTER_FOLD: dict[str, str] = {
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ھ": "ه", "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "آ": "ا", "ؤ": "و",
}
SPACE_FOLD: dict[str, str] = {" ": " ", " ": " "}
DIGIT_FOLD: dict[str, str] = {
    **{ch: str(d) for d, ch in enumerate(PERSIAN_DIGITS)},
    **{ch: str(d) for d, ch in enumerate(ARABIC_INDIC_DIGITS)},
}
# the whole table: single characters only, applied after NFKC
FOLD: dict[str, str] = {**LETTER_FOLD, **SPACE_FOLD, **DIGIT_FOLD, **{ch: "" for ch in IGNORED}}

_TRANSLATE = {ord(k): v for k, v in FOLD.items()}


def fold_text(s: str) -> str:
    """The comparison form of `s` (see the module docstring)."""
    return unicodedata.normalize("NFKC", s).translate(_TRANSLATE)


def variants_of(ch: str) -> str:
    """Every character that compares equal to `ch` (including itself); `ch` itself when it has no variants.
    An ignored character has no class (it matches nothing in particular: callers skip it)."""
    target = FOLD.get(ch, ch)
    if target == "" and ch in FOLD:
        return ""
    return "".join(dict.fromkeys([target, *(k for k, v in FOLD.items() if v == target)]))
