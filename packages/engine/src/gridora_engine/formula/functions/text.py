from __future__ import annotations

import re
from typing import Any

from .. import xlerrors as E
from ..calendars import normalize
from ..numfmt import format_text, format_value, split_sections
from ..values import (
    Arr,
    XlRaise,
    check,
    parse_number,
    to_num,
    to_str,
)
from .helpers import boolean, integer, iter_cells, num, opt_num, scalar, text, wildcard_to_regex
from .registry import fn


@fn("LEN", 1, 1, aliases=("LENB",))
def f_len(ctx: Any, a: Any) -> float:
    return float(len(text(ctx, a)))


@fn("LEFT", 1, 2, aliases=("LEFTB",))
def f_left(ctx: Any, a: Any, n: Any = None) -> str:
    k = int(opt_num(ctx, n, 1))
    if k < 0:
        raise XlRaise(E.VALUE)
    return text(ctx, a)[:k]


@fn("RIGHT", 1, 2, aliases=("RIGHTB",))
def f_right(ctx: Any, a: Any, n: Any = None) -> str:
    k = int(opt_num(ctx, n, 1))
    if k < 0:
        raise XlRaise(E.VALUE)
    s = text(ctx, a)
    return s[max(len(s) - k, 0):] if k else ""


@fn("MID", 3, 3, aliases=("MIDB",))
def f_mid(ctx: Any, a: Any, start: Any, n: Any) -> str:
    s, k = integer(ctx, start), integer(ctx, n)
    if s < 1 or k < 0:
        raise XlRaise(E.VALUE)
    return text(ctx, a)[s - 1 : s - 1 + k]


@fn("UPPER", 1, 1)
def f_upper(ctx: Any, a: Any) -> str:
    return text(ctx, a).upper()


@fn("LOWER", 1, 1)
def f_lower(ctx: Any, a: Any) -> str:
    return text(ctx, a).lower()


@fn("PROPER", 1, 1)
def f_proper(ctx: Any, a: Any) -> str:
    return re.sub(r"[^\W\d_]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text(ctx, a))


@fn("TRIM", 1, 1)
def f_trim(ctx: Any, a: Any) -> str:
    return re.sub(r" +", " ", text(ctx, a).strip(" "))


@fn("CLEAN", 1, 1)
def f_clean(ctx: Any, a: Any) -> str:
    return "".join(ch for ch in text(ctx, a) if ord(ch) >= 32)


@fn("CONCATENATE", 1, -1)
def f_concatenate(ctx: Any, *args: Any) -> str:
    return "".join(text(ctx, a) for a in args)


@fn("CONCAT", 1, -1)
def f_concat(ctx: Any, *args: Any) -> str:
    out = []
    for a in args:
        for x in iter_cells(a):
            out.append(to_str(check(x)))
    return "".join(out)


@fn("TEXTJOIN", 3, -1)
def f_textjoin(ctx: Any, delim: Any, skip: Any, *args: Any) -> str:
    d = text(ctx, delim)
    ign = boolean(ctx, skip)
    parts = []
    for a in args:
        for x in iter_cells(a):
            s = to_str(check(x))
            if ign and s == "":
                continue
            parts.append(s)
    return d.join(parts)


@fn("REPT", 2, 2)
def f_rept(ctx: Any, a: Any, n: Any) -> str:
    k = integer(ctx, n)
    s = text(ctx, a)
    if k < 0 or len(s) * k > 32767:
        raise XlRaise(E.VALUE)
    return s * k


@fn("EXACT", 2, 2)
def f_exact(ctx: Any, a: Any, b: Any) -> bool:
    return text(ctx, a) == text(ctx, b)


@fn("FIND", 2, 3, aliases=("FINDB",))
def f_find(ctx: Any, needle: Any, hay: Any, start: Any = None) -> float:
    n, h = text(ctx, needle), text(ctx, hay)
    s = int(opt_num(ctx, start, 1))
    if s < 1 or s > len(h) + 1:
        raise XlRaise(E.VALUE)
    i = h.find(n, s - 1)
    if i < 0:
        raise XlRaise(E.VALUE)
    return float(i + 1)


@fn("SEARCH", 2, 3, aliases=("SEARCHB",))
def f_search(ctx: Any, needle: Any, hay: Any, start: Any = None) -> float:
    n, h = text(ctx, needle), text(ctx, hay)
    s = int(opt_num(ctx, start, 1))
    if s < 1 or s > len(h) + 1:
        raise XlRaise(E.VALUE)
    m = re.compile(wildcard_to_regex(n), re.IGNORECASE | re.DOTALL).search(h, s - 1)
    if not m:
        raise XlRaise(E.VALUE)
    return float(m.start() + 1)


@fn("SUBSTITUTE", 3, 4)
def f_substitute(ctx: Any, a: Any, old: Any, new: Any, inst: Any = None) -> str:
    s, o, n = text(ctx, a), text(ctx, old), text(ctx, new)
    if o == "":
        return s
    if inst is None:
        return s.replace(o, n)
    k = integer(ctx, inst)
    if k < 1:
        raise XlRaise(E.VALUE)
    idx = -1
    for _ in range(k):
        idx = s.find(o, idx + 1)
        if idx < 0:
            return s
    return s[:idx] + n + s[idx + len(o) :]


@fn("REPLACE", 4, 4, aliases=("REPLACEB",))
def f_replace(ctx: Any, a: Any, start: Any, n: Any, new: Any) -> str:
    s = text(ctx, a)
    i, k = integer(ctx, start), integer(ctx, n)
    if i < 1 or k < 0:
        raise XlRaise(E.VALUE)
    return s[: i - 1] + text(ctx, new) + s[i - 1 + k :]


@fn("VALUE", 1, 1)
def f_value(ctx: Any, a: Any) -> float:
    v = scalar(ctx, a)
    if isinstance(v, str):
        n = parse_number(v)
        if n is None:
            from .datefn import parse_date_text

            d = parse_date_text(v, bool(ctx.env.date1904), normalize(getattr(ctx.env, "calendar", "gregorian")))
            if d is None:
                raise XlRaise(E.VALUE)
            return d
        return n
    return to_num(v)


@fn("NUMBERVALUE", 1, 3)
def f_numbervalue(ctx: Any, a: Any, dec: Any = None, grp: Any = None) -> float:
    s = text(ctx, a).strip().replace(" ", "")
    d = "." if dec is None else text(ctx, dec)
    g = "," if grp is None else text(ctx, grp)
    s = s.replace(g, "").replace(d, ".")
    pct = s.count("%")
    s = s.replace("%", "")
    if s == "":
        return 0.0
    n = parse_number(s)
    if n is None:
        raise XlRaise(E.VALUE)
    scale: float = 100 ** pct
    return n / scale


@fn("TEXT", 2, 2)
def f_text(ctx: Any, a: Any, fmt: Any) -> str:
    v = scalar(ctx, a)
    code = text(ctx, fmt)
    if isinstance(v, str):
        n = parse_number(v)
        if n is None:
            secs = split_sections(code)
            if len(secs) >= 4:
                return format_text(secs[3], v)
            if len(secs) == 1 and "@" in secs[0]:
                return format_text(secs[0], v)
            return v
        v = n
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return format_value(to_num(v), code, bool(ctx.env.date1904), normalize(getattr(ctx.env, "calendar", "gregorian")))


@fn("FIXED", 1, 3)
def f_fixed(ctx: Any, a: Any, d: Any = None, nocomma: Any = None) -> str:
    x = num(ctx, a)
    digits = int(opt_num(ctx, d, 2))
    code = ("0" if (nocomma is not None and boolean(ctx, nocomma)) else "#,##0") + ("." + "0" * digits if digits > 0 else "")
    from ..helpers_round import round_to

    return format_value(round_to(x, digits), code)


@fn("DOLLAR", 1, 2)
def f_dollar(ctx: Any, a: Any, d: Any = None) -> str:
    digits = int(opt_num(ctx, d, 2))
    body = "$#,##0" + ("." + "0" * digits if digits > 0 else "")
    return format_value(num(ctx, a), f"{body};({body})")


@fn("CHAR", 1, 1)
def f_char(ctx: Any, a: Any) -> str:
    n = integer(ctx, a)
    if not 1 <= n <= 255:
        raise XlRaise(E.VALUE)
    return bytes([n]).decode("cp1252", errors="replace")


@fn("CODE", 1, 1)
def f_code(ctx: Any, a: Any) -> float:
    s = text(ctx, a)
    if not s:
        raise XlRaise(E.VALUE)
    try:
        return float(s[0].encode("cp1252")[0])
    except UnicodeEncodeError:
        return 63.0


@fn("UNICHAR", 1, 1)
def f_unichar(ctx: Any, a: Any) -> str:
    n = integer(ctx, a)
    if n < 1 or n > 0x10FFFF or 0xD800 <= n <= 0xDFFF:
        raise XlRaise(E.VALUE)
    return chr(n)


@fn("UNICODE", 1, 1)
def f_unicode(ctx: Any, a: Any) -> float:
    s = text(ctx, a)
    if not s:
        raise XlRaise(E.VALUE)
    return float(ord(s[0]))


@fn("TEXTBEFORE", 2, 4)
def f_textbefore(ctx: Any, a: Any, delim: Any, inst: Any = None, mode: Any = None) -> str:
    s, d = text(ctx, a), text(ctx, delim)
    k = int(opt_num(ctx, inst, 1))
    ci = bool(opt_num(ctx, mode, 0))
    hay = s.lower() if ci else s
    nd = d.lower() if ci else d
    if not nd or k == 0:
        raise XlRaise(E.VALUE)
    idx = _nth(hay, nd, k)
    if idx < 0:
        raise XlRaise(E.NA)
    return s[:idx]


@fn("TEXTAFTER", 2, 4)
def f_textafter(ctx: Any, a: Any, delim: Any, inst: Any = None, mode: Any = None) -> str:
    s, d = text(ctx, a), text(ctx, delim)
    k = int(opt_num(ctx, inst, 1))
    ci = bool(opt_num(ctx, mode, 0))
    hay = s.lower() if ci else s
    nd = d.lower() if ci else d
    if not nd or k == 0:
        raise XlRaise(E.VALUE)
    idx = _nth(hay, nd, k)
    if idx < 0:
        raise XlRaise(E.NA)
    return s[idx + len(d) :]


def _nth(hay: str, needle: str, k: int) -> int:
    if k > 0:
        idx = -1
        for _ in range(k):
            idx = hay.find(needle, idx + 1)
            if idx < 0:
                return -1
        return idx
    idx = len(hay)
    for _ in range(-k):
        idx = hay.rfind(needle, 0, idx)
        if idx < 0:
            return -1
    return idx


@fn("TEXTSPLIT", 2, 6, arr=True)
def f_textsplit(ctx: Any, a: Any, coldelim: Any, rowdelim: Any = None) -> Arr:
    s = text(ctx, a)
    cd = text(ctx, coldelim)
    rd = None if rowdelim is None else text(ctx, rowdelim)
    rows = s.split(rd) if rd else [s]
    out = [r.split(cd) if cd else [r] for r in rows]
    width = max(len(r) for r in out)
    return Arr([r + [E.NA] * (width - len(r)) for r in out])
