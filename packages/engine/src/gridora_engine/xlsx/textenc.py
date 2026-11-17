"""OOXML text escapes: `_xHHHH_` sequences (ECMA-376 22.4.2.4) and XML escaping."""
from __future__ import annotations

import re

_X_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")
_NEEDS_ESCAPE = re.compile("[\x00-\x08\x0b\x0c\x0d\x0e-\x1f\ufffe\uffff\ud800-\udfff]")


def decode_text(s: str) -> str:
    """Read side: `_x000D_` -> CR, `_x005F_` -> `_` (surrogate halves are joined when paired)."""
    if "_x" not in s:
        return s
    out = _X_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s)
    if any("\ud800" <= ch <= "\udfff" for ch in out):
        out = out.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return out


def encode_text(s: str) -> str:
    """Write side: characters XML 1.0 cannot carry (and CR, which parsers normalize) become
    `_xHHHH_`; a literal `_xHHHH_` in the text is protected as `_x005F_xHHHH_`; then XML-escaped."""
    out: list[str] = []
    for i, ch in enumerate(s):
        if _NEEDS_ESCAPE.match(ch):
            out.append(f"_x{ord(ch):04X}_")
        elif ch == "_" and _X_ESCAPE.match(s, i):
            out.append("_x005F_")
        elif ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        else:
            out.append(ch)
    return "".join(out)


def xml_escape(s: str) -> str:
    """Escaping for formula text and attributes (no `_x` handling)."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def col_letters(c: int) -> str:
    """0-based column index -> 'A', 'B', ..., 'XFD'."""
    n = c + 1
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out
