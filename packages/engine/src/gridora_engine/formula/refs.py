"""A1 reference helpers."""
from __future__ import annotations

import re

MAX_ROWS = 1_048_576
MAX_COLS = 16_384

CELL_RE = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$")


def col_to_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def index_to_col(i: int) -> str:
    i += 1
    out = ""
    while i:
        i, rem = divmod(i - 1, 26)
        out = chr(65 + rem) + out
    return out


def parse_cell(text: str) -> tuple[int, int, bool, bool] | None:
    """'$B$7' -> (row0, col0, row_abs, col_abs); None when not a valid cell address."""
    m = CELL_RE.match(text)
    if not m:
        return None
    c = col_to_index(m.group(2))
    r = int(m.group(4)) - 1
    if c >= MAX_COLS or r < 0 or r >= MAX_ROWS:
        return None
    return r, c, bool(m.group(3)), bool(m.group(1))


def cell_text(r: int, c: int, row_abs: bool = False, col_abs: bool = False) -> str:
    return f"{'$' if col_abs else ''}{index_to_col(c)}{'$' if row_abs else ''}{r + 1}"
