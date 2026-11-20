"""Number-format engine for TEXT() (subset: numbers, percent, grouping, sci, dates, times)."""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from .dates import split_time, serial_to_ymd, weekday
from .values import num_to_text

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

_TOKEN = re.compile(
    r'"(?P<q>[^"]*)"|\\(?P<esc>.)|_(?P<sp>.)|\*(?P<fill>.)|\[(?P<br>[^\]]*)\]|'
    r"(?P<ampm>AM/PM|am/pm|A/P|a/p)|(?P<date>[yYdDhHsS]+|[mM]+)|(?P<sci>[eE][+-])|(?P<ch>.)"
)


def split_sections(code: str) -> list[str]:
    parts, cur, inq = [], [], False
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
    return bool(re.search(r"[ydhsmYDHSM]", s)) and not re.search(r"^\s*general\s*$", s, re.I)


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


def format_value(v: float, code: str, date1904: bool = False) -> str:
    if code.strip().lower() in ("", "general"):
        return general_text(v)
    secs = split_sections(code)
    sec = secs[0]
    neg_section = False
    if v < 0 and len(secs) > 1:
        sec, neg_section = secs[1], True
    elif v == 0 and len(secs) > 2:
        sec = secs[2]
    if is_date_code(sec):
        return _format_date(v, sec, date1904)
    return _format_number(-v if (neg_section or (v < 0 and len(secs) > 1)) and neg_section else v, sec, neg_section)


# -- numbers ----------------------------------------------------------------------------------------
def _format_number(v: float, sec: str, explicit_neg: bool) -> str:
    sec = re.sub(r"\[(?:Red|Black|Blue|Green|Cyan|Magenta|White|Yellow|Color\d+)\]", "", sec, flags=re.I)
    toks = [m for m in _TOKEN.finditer(sec)]
    pct = sum(1 for m in toks if m.group("ch") == "%")
    has_sci = any(m.group("sci") for m in toks)
    neg = v < 0
    dx = Decimal(repr(abs(v))) * (Decimal(100) ** pct) if v == v and not math.isinf(v) else Decimal(0)
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
    grouping = "," in int_part
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
    rounded = d.quantize(Decimal(1).scaleb(-nfrac), rounding=ROUND_HALF_UP)
    s = f"{rounded:f}"
    s_int, _, s_frac = s.partition(".")
    s_int = s_int.lstrip("0") if len(int_digits.replace("#", "")) == 0 or True else s_int
    min_int = int_digits.count("0")
    s_int = s_int.rjust(min_int, "0")
    # '?' pads with spaces
    q = int_digits.count("?")
    if q:
        s_int = s_int.rjust(len(s_int) + 0, " ")
    if grouping and s_int:
        s_int = f"{int(s_int):,}" if s_int.strip().isdigit() else s_int
    if nfrac:
        # trim optional trailing '#' fraction digits
        req = frac_part.replace(",", "")
        keep = len(req)
        while keep > 0 and req[keep - 1] == "#" and s_frac[keep - 1 : keep] == "0":
            keep -= 1
        s_frac = s_frac[:keep]
    digits = s_int + ("." + s_frac if s_frac else "")
    if not int_digits and not s_frac:
        digits = ""
    if digits.startswith(".") is False and s_int == "" and not nfrac and int_digits:
        digits = ""
    is_zero = rounded == 0
    return _assemble_literal(toks, digits, neg and not is_zero and not explicit_neg, simple=False)


def _assemble_literal(toks, digits: str, negative: bool, simple: bool) -> str:
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
        elif m.group("fill") is not None or m.group("br") is not None:
            continue
        elif m.group("sci"):
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
def _format_date(v: float, sec: str, date1904: bool) -> str:
    sec = re.sub(r"\[\$[^\]]*\]|\[(?:Red|Black|Blue|Green|Cyan|Magenta|White|Yellow)\]", "", sec, flags=re.I)
    toks = list(_TOKEN.finditer(sec))
    elapsed = any(m.group("br") and re.fullmatch(r"[hmsHMS]+", m.group("br")) for m in toks)
    y, mo, d = serial_to_ymd(v, date1904)
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
                out.append(str(int(math.floor(v * 24))).zfill(len(b)))
            elif re.fullmatch(r"[mM]+", b):
                out.append(str(int(math.floor(v * 1440))).zfill(len(b)))
            elif re.fullmatch(r"[sS]+", b):
                out.append(str(int(round(v * 86400))).zfill(len(b)))
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
                out.append(str(d) if n == 1 else str(d).zfill(2) if n == 2 else (DAYS[wd - 1][:3] if n == 3 else DAYS[wd - 1]))
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
                    out.append(MONTHS[mo - 1][:3])
                elif n == 4:
                    out.append(MONTHS[mo - 1])
                else:
                    out.append(MONTHS[mo - 1][0])
        else:
            out.append(m.group("ch") or "")
    return "".join(out)


def _is_minute(toks, idx: int) -> bool:
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
