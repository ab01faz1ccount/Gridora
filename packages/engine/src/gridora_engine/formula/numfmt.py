"""Number-format engine for TEXT() (subset: numbers, percent, grouping, sci, dates, times)."""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, getcontext

from .calendars import PERSIAN_DAYS, month_names
from .dates import serial_to_cal, split_time, weekday

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

_TOKEN = re.compile(
    r'"(?P<q>[^"]*)"|\\(?P<esc>.)|_(?P<sp>.)|\*(?P<fill>.)|\[(?P<br>[^\]]*)\]|'
    r"(?P<ampm>AM/PM|am/pm|A/P|a/p)|(?P<date>[yYdDhHsS]+|[mM]+)|(?P<sci>[eE][+-])|(?P<ch>.)"
)


def split_sections(code: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    inq = False
    for ch in code:
        if ch == '"':
            inq = not inq
        if ch == ";" and not inq:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def is_date_code(section: str) -> bool:
    s = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", section)
    return bool(re.search(r"[ydhsmYDHSM]", s)) and not re.search(r"^\s*general\s*$", s, re.IGNORECASE)


def general_text(v: float) -> str:
    """Excel's General format: at most 11 characters, scientific beyond that."""
    if v == 0:
        return "0"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e11 or a < 1e-4:
        mant, exp = f"{a:.5E}".split("E")
        mant = mant.rstrip("0").rstrip(".")
        e = int(exp)
        return f"{sign}{mant}E{'-' if e < 0 else '+'}{abs(e):02d}"
    int_digits = len(str(int(a)))
    decimals = max(10 - int_digits, 0) if a >= 1 else 9
    d = Decimal(repr(a)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    s = f"{d:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return sign + s


def format_value(v: float, code: str, date1904: bool = False, cal: str = "gregorian") -> str:
    getcontext().prec = max(getcontext().prec, 400)
    if code.strip().lower() in ("", "general"):
        return general_text(v)
    secs = split_sections(code)
    sec, conditional = _pick_section(v, secs)
    neg_section = v < 0 and not conditional and len(secs) > 1
    if is_date_code(sec):
        return _format_date(v, sec, date1904, cal)
    if "@" in re.sub(r'"[^"]*"|\\.', "", sec):  # a text section applied to a number
        return format_text(sec, general_text(v))
    return _format_number(-v if neg_section else v, sec, neg_section)


_COND = re.compile(r"^\s*\[\s*(<=|>=|<>|<|>|=)\s*(-?[0-9.]+(?:[eE][+-]?\d+)?)\s*\]")


def _cond(sec: str) -> tuple[str, float] | None:
    m = _COND.match(re.sub(r"\[(?:Red|Black|Blue|Green|Cyan|Magenta|White|Yellow|Color\d+)\]", "", sec, flags=re.IGNORECASE))
    return (m.group(1), float(m.group(2))) if m else None


def _holds(v: float, c: tuple[str, float]) -> bool:
    op, n = c
    return {"<": v < n, ">": v > n, "<=": v <= n, ">=": v >= n, "=": v == n, "<>": v != n}[op]


def _pick_section(v: float, secs: list[str]) -> tuple[str, bool]:
    """The section of a number format that applies to `v` (plain: positive; negative; zero; conditions win)."""
    c0 = _cond(secs[0])
    c1 = _cond(secs[1]) if len(secs) > 1 else None
    if c0 is not None or c1 is not None:
        if c0 is not None and _holds(v, c0):
            return secs[0], True
        if len(secs) > 1 and c1 is not None and _holds(v, c1):
            return secs[1], True
        if len(secs) > 2:
            return secs[2], True
        if len(secs) == 2 and c1 is None:
            return secs[1], True  # "[>100]0;0": everything else
        return secs[0], True
    if v < 0 and len(secs) > 1:
        return secs[1], False
    if v == 0 and len(secs) > 2:
        return secs[2], False
    return secs[0], False


def format_text(sec: str, v: str) -> str:
    """A text section: `@` stands for the text, quoted and escaped characters are literal."""
    out: list[str] = []
    for m in _TOKEN.finditer(sec):
        if m.group("q") is not None:
            out.append(m.group("q"))
        elif m.group("esc") is not None:
            out.append(m.group("esc"))
        elif m.group("sp") is not None:
            out.append(" ")
        elif m.group("ch") == "@":
            out.append(v)
        elif m.group("ch") is not None:
            out.append(m.group("ch"))
    return "".join(out)


# -- numbers ----------------------------------------------------------------------------------------
def _format_number(v: float, sec: str, explicit_neg: bool) -> str:
    sec = re.sub(r"\[(?:Red|Black|Blue|Green|Cyan|Magenta|White|Yellow|Color\d+)\]", "", sec, flags=re.IGNORECASE)
    toks = [m for m in _TOKEN.finditer(sec)]
    pct = sum(1 for m in toks if m.group("ch") == "%")
    has_sci = any(m.group("sci") for m in toks)
    neg = v < 0
    dx = Decimal(repr(abs(v))) * (Decimal(100) ** pct) if not math.isnan(v) and not math.isinf(v) else Decimal(0)
    # find the numeric pattern span (digit placeholders, '.', ',')
    pat = []
    for m in toks:
        if m.group("sci"):
            break
        ch = m.group("ch")
        if ch is not None and ch in "0#?.,":
            pat.append(m)
    body = "".join(m.group("ch") for m in pat)
    scale = len(body) - len(body.rstrip(","))  # commas after the last digit placeholder scale by 1000
    body = body.rstrip(",")
    int_part, _, frac_part = body.partition(".")
    grouping = bool(re.search(r"[0#?],+[0#?]", int_part)) or (
        "," in int_part.rstrip(",") and int_part.strip(",") != "" and int_part[0] != ","
    )
    int_digits = int_part.replace(",", "")
    nfrac = len(frac_part.replace(",", ""))
    dx = dx / (Decimal(1000) ** scale)
    sci_exp_digits = 0
    sci_sign = ""
    if has_sci:
        m = next(m for m in toks if m.group("sci"))
        idx = toks.index(m)
        sci_sign = m.group("sci")[1]
        sci_exp_digits = sum(1 for t in toks[idx + 1 :] if t.group("ch") == "0")
    d = dx
    if has_sci:
        exp = 0
        if d != 0:
            exp = d.adjusted()
            lead = max(len(int_digits), 1)
            exp -= lead - 1
            d = d.scaleb(-exp)
        rounded = d.quantize(Decimal(1).scaleb(-nfrac), rounding=ROUND_HALF_UP)
        s_int, _, s_frac = f"{rounded:f}".partition(".")
        mant = s_int + ("." + s_frac if nfrac else "")
        es = ("-" if exp < 0 else ("+" if sci_sign == "+" else "")) + str(abs(exp)).zfill(sci_exp_digits)
        out_digits = mant + "E" + es
        return _assemble_literal(toks, out_digits, neg and not explicit_neg, simple=True)
    if any(m.group("ch") == "/" for m in toks) and _fraction_layout(toks) is not None:
        return _format_fraction(d, toks, neg and not explicit_neg)
    rounded = d.quantize(Decimal(1).scaleb(-nfrac), rounding=ROUND_HALF_UP)
    s_int, _, s_frac = f"{rounded:f}".partition(".")
    s_int = s_int.lstrip("0")
    if not pat:  # no digit placeholders: the section is only text
        s_int = s_frac = ""
    is_zero = rounded == 0
    out = _layout(toks, s_int, s_frac, grouping)
    return ("-" + out) if (neg and not is_zero and not explicit_neg) else out


def _is_ph(m: re.Match[str]) -> bool:
    ch = m.group("ch")
    return ch is not None and ch in "0#?"


def _layout(toks: list[re.Match[str]], s_int: str, s_frac: str, grouping: bool) -> str:
    """Place digits into the 0/#/? placeholders; literals stay where they are written."""
    # trailing commas (scale) and grouping commas never print
    dot = next((i for i, m in enumerate(toks) if m.group("ch") == "."), None)
    int_idx = [i for i, m in enumerate(toks) if _is_ph(m) and (dot is None or i < dot)]
    frac_idx = [i for i, m in enumerate(toks) if _is_ph(m) and dot is not None and i > dot]
    piece: dict[int, str] = {}
    first_ph = next((i for i, m in enumerate(toks) if _is_ph(m)), None)
    # integer part: right to left, overflow goes to the leftmost placeholder
    digits = list(s_int)
    for pos, i in enumerate(reversed(int_idx)):
        kind = toks[i].group("ch")
        if digits:
            piece[i] = digits.pop()
        else:
            piece[i] = "0" if kind == "0" else (" " if kind == "?" else "")
    prefix = "".join(digits)
    if int_idx:
        piece[int_idx[0]] = prefix + piece[int_idx[0]]
    elif prefix:
        piece[dot if dot is not None else 0] = prefix  # no integer placeholder: digits go in front of the point
    if grouping:
        joined = [(i, piece[i]) for i in int_idx]
        stream = "".join(p for _, p in joined)
        digs = [c for c in stream if c.isdigit()]
        if len(digs) > 3:
            count = 0
            # insert a comma before every group of three digits counted from the right
            rev: list[str] = []
            for i, p in reversed(joined):
                chars: list[str] = []
                for c in reversed(p):
                    if c.isdigit():
                        if count and count % 3 == 0:
                            chars.append(",")
                        count += 1
                    chars.append(c)
                rev.append("".join(reversed(chars)))
            for (i, _), val in zip(reversed(joined), rev, strict=True):
                piece[i] = val
    # fraction digits, left to right; trailing optional placeholders drop zeros
    fd = list(s_frac.ljust(len(frac_idx), "0"))
    last_sig = max((k for k, c in enumerate(fd) if c != "0"), default=-1)
    for k, i in enumerate(frac_idx):
        kind = toks[i].group("ch")
        if kind == "0" or k <= last_sig:
            piece[i] = fd[k]
        else:
            piece[i] = " " if kind == "?" else ""
    out: list[str] = []
    for i, m in enumerate(toks):
        ch = m.group("ch")
        if i in piece:
            out.append(piece[i])
        elif m.group("q") is not None:
            out.append(m.group("q"))
        elif m.group("esc") is not None:
            out.append(m.group("esc"))
        elif m.group("sp") is not None:
            out.append(" ")
        elif m.group("fill") is not None or m.group("br") is not None or m.group("sci"):
            continue
        elif ch == ".":
            out.append(".")
        elif ch == ",":
            if first_ph is None or i < first_ph:
                out.append(",")  # a comma before every digit placeholder is an ordinary character
        elif ch is not None:
            out.append(ch)
    return "".join(out)


def _fraction_layout(toks: list[re.Match[str]]) -> tuple[list[int], list[int], list[int], int] | None:
    """(int placeholder idx, numerator idx, denominator idx, slash idx) of a fraction format, else None."""
    slash = next((i for i, m in enumerate(toks) if m.group("ch") == "/"), None)
    if slash is None:
        return None
    num: list[int] = []
    i = slash - 1
    while i >= 0 and _is_ph(toks[i]):
        num.append(i)
        i -= 1
    den: list[int] = []
    j = slash + 1
    while j < len(toks) and (_is_ph(toks[j]) or (toks[j].group("ch") or "").isdigit()):
        den.append(j)
        j += 1
    if not num or not den:
        return None
    num.reverse()
    ints = [k for k in range(num[0]) if _is_ph(toks[k])]
    return ints, num, den, slash


def _best_fraction(x: Decimal, max_den: int, fixed: int | None) -> tuple[int, int]:
    if fixed is not None:
        return int((x * fixed).quantize(Decimal(1), rounding=ROUND_HALF_UP)), fixed
    best = (int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP)), 1)
    best_err = abs(x - best[0])
    for d in range(2, max_den + 1):
        n = int((x * d).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        err = abs(x - Decimal(n) / Decimal(d))
        if err < best_err:
            best, best_err = (n, d), err
    return best


def _format_fraction(d: Decimal, toks: list[re.Match[str]], negative: bool) -> str:
    ints, num, den, slash = _fraction_layout(toks)  # type: ignore[misc]
    den_text = "".join(toks[k].group("ch") for k in den)
    fixed = int(den_text) if den_text.isdigit() else None
    max_den = 10 ** len(den) - 1
    mixed = bool(ints)
    ip = int(d) if mixed else 0
    rest = d - ip
    n, dd = _best_fraction(rest, max_den, fixed)
    if mixed and n == dd:  # rounds up to a whole number
        ip, n = ip + 1, 0
    if not mixed:
        n, dd = _best_fraction(d, max_den, fixed)
    zero_frac = mixed and n == 0

    def fill(idx: list[int], text: str, left: bool) -> str:
        cells = []
        digs = list(text)
        for k in (reversed(idx) if left else idx):
            kind = toks[k].group("ch")
            if kind in "0#?" and digs:
                cells.append(digs.pop() if left else digs.pop(0))
            else:
                cells.append("0" if kind == "0" else (" " if kind == "?" else ""))
        cells = cells[::-1] if left else cells
        extra = "".join(digs)
        return extra + "".join(cells) if left else "".join(cells) + extra

    int_text = fill(ints, str(ip) if (ip or not mixed) else "", True) if mixed else ""
    if mixed and ip == 0:
        int_text = fill(ints, "", True)
        if any(toks[k].group("ch") == "0" for k in ints):
            int_text = fill(ints, "0", True)
    num_text = fill(num, str(n), True)
    den_text2 = fill(den, str(dd), False) if fixed is None else den_text
    first = ints[0] if ints else num[0]
    out: list[str] = []
    for i, m in enumerate(toks):
        if i < first:
            if m.group("q") is not None:
                out.append(m.group("q"))
            elif m.group("esc") is not None:
                out.append(m.group("esc"))
            elif m.group("sp") is not None:
                out.append(" ")
            elif m.group("ch") is not None and m.group("ch") not in ",":
                out.append(m.group("ch"))
            continue
        if ints and i == ints[0]:
            out.append(int_text)
        elif i in ints or i in num[1:] or i in den[1:]:
            continue
        elif i == num[0]:
            out.append(" " * (len(num_text) + 1 + len(den_text2)) if zero_frac else num_text)
        elif i == slash:
            out.append("" if zero_frac else "/")
        elif i == den[0]:
            out.append("" if zero_frac else den_text2)
        elif m.group("q") is not None:
            out.append(m.group("q"))
        elif m.group("esc") is not None:
            out.append(m.group("esc"))
        elif m.group("sp") is not None:
            out.append(" ")
        elif m.group("ch") is not None and m.group("ch") not in ",.":
            out.append(m.group("ch"))
    s = "".join(out)
    return ("-" + s) if negative and (ip or n) else s


def _assemble_literal(toks: list[re.Match[str]], digits: str, negative: bool, simple: bool) -> str:
    out: list[str] = []
    placed = False
    for m in toks:
        ch = m.group("ch")
        if m.group("q") is not None:
            out.append(m.group("q"))
        elif m.group("esc") is not None:
            out.append(m.group("esc"))
        elif m.group("sp") is not None:
            out.append(" ")
        elif m.group("fill") is not None or m.group("br") is not None or m.group("sci"):
            continue
        elif ch is not None and (ch in "0#?.," or (simple and ch in "0#?.,")):
            if not placed:
                out.append(digits)
                placed = True
        elif ch == "%":
            out.append("%")
        elif ch is not None:
            out.append(ch)
    s = "".join(out)
    if not placed:
        s = digits + s if digits else s
    return ("-" + s) if negative else s


# -- dates ------------------------------------------------------------------------------------------------
def _format_date(v: float, sec: str, date1904: bool, cal: str = "gregorian") -> str:
    sec = re.sub(r"\[\$[^\]]*\]|\[(?:Red|Black|Blue|Green|Cyan|Magenta|White|Yellow)\]", "", sec, flags=re.IGNORECASE)
    toks = list(_TOKEN.finditer(sec))
    any(m.group("br") and re.fullmatch(r"[hmsHMS]+", m.group("br")) for m in toks)
    y, mo, d = serial_to_cal(v, cal, date1904)
    names = month_names(cal)
    hh, mi, ss = split_time(v)
    ampm = any(m.group("ampm") for m in toks)
    wd = weekday(v, date1904)
    out: list[str] = []
    for idx, m in enumerate(toks):
        if m.group("q") is not None:
            out.append(m.group("q"))
        elif m.group("esc") is not None:
            out.append(m.group("esc"))
        elif m.group("sp") is not None:
            out.append(" ")
        elif m.group("fill") is not None:
            continue
        elif m.group("br") is not None:
            b = m.group("br")
            if re.fullmatch(r"[hH]+", b):
                out.append(str(math.floor(v * 24)).zfill(len(b)))
            elif re.fullmatch(r"[mM]+", b):
                out.append(str(math.floor(v * 1440)).zfill(len(b)))
            elif re.fullmatch(r"[sS]+", b):
                out.append(str(round(v * 86400)).zfill(len(b)))
        elif m.group("ampm"):
            a = m.group("ampm")
            pm = hh >= 12
            if a.upper() == "AM/PM":
                out.append(("PM" if pm else "AM") if a.isupper() else ("pm" if pm else "am"))
            else:
                out.append(("P" if pm else "A") if a.isupper() else ("p" if pm else "a"))
        elif m.group("date"):
            t = m.group("date")
            c = t[0].lower()
            n = len(t)
            if c == "y":
                out.append(str(y).zfill(4) if n >= 3 else str(y % 100).zfill(2))
            elif c == "d":
                out.append(str(d) if n == 1 else str(d).zfill(2) if n == 2 else ((PERSIAN_DAYS if names else DAYS)[wd - 1][: 3 if not names else None] if n == 3 else (PERSIAN_DAYS if names else DAYS)[wd - 1]))
            elif c == "h":
                h = hh % 12 or 12 if ampm else hh
                out.append(str(h).zfill(n))
            elif c == "s":
                out.append(str(ss).zfill(n))
            elif c == "m":
                if _is_minute(toks, idx):
                    out.append(str(mi).zfill(min(n, 2)))
                elif n == 1:
                    out.append(str(mo))
                elif n == 2:
                    out.append(str(mo).zfill(2))
                elif n == 3:
                    out.append((names or MONTHS)[mo - 1][: None if names else 3])
                elif n == 4:
                    out.append((names or MONTHS)[mo - 1])
                else:
                    out.append((names or MONTHS)[mo - 1][0])
        else:
            out.append(m.group("ch") or "")
    return "".join(out)


def _is_minute(toks: list[re.Match[str]], idx: int) -> bool:
    """'m' is minutes when the nearest date/time token before it is h, or the next one is s."""
    for t in reversed(toks[:idx]):
        g = t.group("date")
        if g or (t.group("br") and re.fullmatch(r"[hH]+", t.group("br") or "")):
            if g and g[0].lower() in "ymd":
                break
            if (g and g[0].lower() == "h") or t.group("br"):
                return True
            break
    for t in toks[idx + 1 :]:
        g = t.group("date")
        if g:
            return g[0].lower() == "s"
    return False
