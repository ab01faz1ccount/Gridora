"""Lexer and Pratt parser for Excel formulas (text without the leading '=')."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .refs import MAX_COLS, MAX_ROWS, CELL_RE, col_to_index, parse_cell
from .xlerrors import BY_CODE


class FormulaSyntaxError(ValueError):
    pass


# -- AST ---------------------------------------------------------------------------------------
@dataclass(slots=True)
class Num:
    v: float


@dataclass(slots=True)
class Str:
    v: str


@dataclass(slots=True)
class Bool:
    v: bool


@dataclass(slots=True)
class Err:
    code: str


@dataclass(slots=True)
class Ref:
    """Rectangle on a sheet. sheet=None means the formula's own sheet. Corners are 0-based and
    inclusive; full-column / full-row references use the sheet limits (flags keep the intent)."""

    sheet: str | None
    r0: int
    c0: int
    r1: int
    c1: int
    abs_r0: bool = False
    abs_c0: bool = False
    abs_r1: bool = False
    abs_c1: bool = False
    full_col: bool = False
    full_row: bool = False


@dataclass(slots=True)
class Name:
    name: str


@dataclass(slots=True)
class StructRef:
    """Table structured reference, e.g. Table1[[#This Row],[Qty]]. Resolved to a Ref per formula cell
    by the calculation layer (it needs the table definitions)."""

    table: str | None
    items: list[str]  # subset of ALL DATA HEADERS TOTALS THIS_ROW; empty = data rows
    col1: str | None = None
    col2: str | None = None


@dataclass(slots=True)
class Func:
    name: str
    args: list["Node"]


@dataclass(slots=True)
class Unary:
    op: str
    x: "Node"


@dataclass(slots=True)
class Percent:
    x: "Node"


@dataclass(slots=True)
class Binary:
    op: str
    a: "Node"
    b: "Node"


@dataclass(slots=True)
class ArrayLit:
    rows: list[list["Node"]]


@dataclass(slots=True)
class Missing:
    """An omitted argument: IF(A1,,2)."""


Node = Num | Str | Bool | Err | Ref | Name | StructRef | Func | Unary | Percent | Binary | ArrayLit | Missing

# -- lexer -------------------------------------------------------------------------------------
_SHEET = r"(?:'(?:[^']|'')+'|[^\W\d][\w\.]*)!"
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_COL = r"\$?[A-Za-z]{1,3}"
_ROW = r"\$?\d+"
_AREA = rf"(?:{_CELL}(?::{_CELL})?|{_COL}:{_COL}|{_ROW}:{_ROW})"
_BOUND = r"(?![\w\.\(!\[])"
REF_RE = re.compile(rf"(?P<sheet>{_SHEET})?(?P<area>{_AREA}){_BOUND}")
NUM_RE = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
IDENT_RE = re.compile(r"[^\W\d][\w\.]*|\\[\w\.]*")
ERR_RE = re.compile(r"#(?:DIV/0!|N/A|NAME\?|NULL!|NUM!|REF!|VALUE!|SPILL!|CALC!|GETTING_DATA)", re.I)
OPS = ("<>", "<=", ">=", "=", "<", ">", "+", "-", "*", "/", "^", "&", ":", "%")


@dataclass(slots=True)
class Tok:
    kind: str  # num str err ref name func bool op ( ) , ; { } end
    text: str
    pos: int
    end: int = 0
    value: object = None


def tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == '"':
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise FormulaSyntaxError("unterminated string")
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(src[j])
                j += 1
            toks.append(Tok("str", src[i : j + 1], i, j + 1, "".join(buf)))
            i = j + 1
            continue
        if ch == "#":
            m = ERR_RE.match(src, i)
            if not m:
                raise FormulaSyntaxError("bad error literal")
            toks.append(Tok("err", m.group(), i, m.end(), m.group().upper()))
            i = m.end()
            continue
        if ch == "[":
            if re.match(r"\[\d+\]", src[i:]):
                raise FormulaSyntaxError("external references are not supported")
            j = _bracket_end(src, i)
            toks.append(Tok("struct", src[i:j], i, j, (None, src[i:j])))
            i = j
            continue
        m = REF_RE.match(src, i)
        if m and (m.group("sheet") or not _starts_number_like(src, i, m)):
            toks.append(Tok("ref", m.group(), i, m.end(), (m.group("sheet"), m.group("area"))))
            i = m.end()
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            m = NUM_RE.match(src, i)
            assert m
            toks.append(Tok("num", m.group(), i, m.end(), float(m.group())))
            i = m.end()
            continue
        m = IDENT_RE.match(src, i)
        if m:
            text = m.group()
            j = m.end()
            if j < n and src[j] == "!":
                raise FormulaSyntaxError("unsupported sheet reference")
            if j < n and src[j] == "[":
                e = _bracket_end(src, j)
                toks.append(Tok("struct", src[i:e], i, e, (text, src[j:e])))
                i = e
                continue
            k = j
            while k < n and src[k] in " \t":
                k += 1
            if k < n and src[k] == "(":
                toks.append(Tok("func", text, i, j))
            elif text.upper() in ("TRUE", "FALSE"):
                toks.append(Tok("bool", text, i, j, text.upper() == "TRUE"))
            else:
                toks.append(Tok("name", text, i, j))
            i = j
            continue
        if ch in "(),;{}":
            toks.append(Tok(ch, ch, i, i + 1))
            i += 1
            continue
        for op in OPS:
            if src.startswith(op, i):
                toks.append(Tok("op", op, i, i + len(op)))
                i += len(op)
                break
        else:
            raise FormulaSyntaxError(f"unexpected character {ch!r}")
    toks.append(Tok("end", "", n, n))
    return toks


def _bracket_end(src: str, i: int) -> int:
    """Index just past the ']' matching the '[' at i (a ' escapes the next character)."""
    depth, j, n = 0, i, len(src)
    while j < n:
        ch = src[j]
        if ch == "'":
            j += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise FormulaSyntaxError("unterminated structured reference")


def _unescape(s: str) -> str:
    return re.sub(r"'(.)", r"\1", s)


_KEYWORDS = {"#ALL": "ALL", "#DATA": "DATA", "#HEADERS": "HEADERS", "#TOTALS": "TOTALS", "#THIS ROW": "THIS_ROW"}


def parse_struct(table: str | None, text: str) -> "StructRef":
    inner = text[1:-1]
    items: list[str] = []
    cols: list[str] = []

    def add(piece: str) -> None:
        piece = piece.strip()
        if piece.startswith("[") and piece.endswith("]"):
            piece = piece[1:-1]
        key = _KEYWORDS.get(piece.strip().upper())
        if key:
            items.append(key)
        elif piece:
            cols.append(_unescape(piece))

    if inner.startswith("@"):
        items.append("THIS_ROW")
        rest = inner[1:]
        if rest:
            add(rest)
    elif "[" in inner:
        # top level pieces: [a],[b] or [a]:[b]
        depth, cur, parts = 0, [], []
        j = 0
        while j < len(inner):
            ch = inner[j]
            if ch == "'":
                cur.append(inner[j : j + 2])
                j += 2
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            if depth == 0 and ch in ",:":
                parts.append("".join(cur))
                if ch == ":":
                    parts.append(":")
                cur = []
            else:
                cur.append(ch)
            j += 1
        parts.append("".join(cur))
        for p in parts:
            if p == ":":
                continue
            add(p)
    else:
        add(inner)
    if len(cols) > 2 or not all(it in {"ALL", "DATA", "HEADERS", "TOTALS", "THIS_ROW"} for it in items):
        raise FormulaSyntaxError("unsupported structured reference")
    return StructRef(table, items, cols[0] if cols else None, cols[1] if len(cols) > 1 else None)


def _starts_number_like(src: str, i: int, m: re.Match[str]) -> bool:
    """A row range such as 1:3 is a ref; a bare number is not (handled by REF_RE needing ':')."""
    return False


# -- reference parsing ---------------------------------------------------------------------------
def _unquote_sheet(s: str | None) -> str | None:
    if s is None:
        return None
    s = s[:-1]  # drop '!'
    if s.startswith("'"):
        s = s[1:-1].replace("''", "'")
    return s


def make_ref(sheet_text: str | None, area: str) -> Ref:
    sheet = _unquote_sheet(sheet_text)
    parts = area.split(":")
    if len(parts) == 1:
        p = parse_cell(parts[0])
        if p is None:
            raise FormulaSyntaxError("bad cell reference")
        r, c, ra, ca = p
        return Ref(sheet, r, c, r, c, ra, ca, ra, ca)
    a, b = parts
    pa, pb = parse_cell(a), parse_cell(b)
    if pa and pb:
        (r0, c0, ra0, ca0), (r1, c1, ra1, ca1) = pa, pb
        if r0 > r1:
            r0, r1, ra0, ra1 = r1, r0, ra1, ra0
        if c0 > c1:
            c0, c1, ca0, ca1 = c1, c0, ca1, ca0
        return Ref(sheet, r0, c0, r1, c1, ra0, ca0, ra1, ca1)
    ma, mb = re.fullmatch(r"(\$?)([A-Za-z]{1,3})", a), re.fullmatch(r"(\$?)([A-Za-z]{1,3})", b)
    if ma and mb:
        c0, c1 = col_to_index(ma.group(2)), col_to_index(mb.group(2))
        if c0 >= MAX_COLS or c1 >= MAX_COLS:
            raise FormulaSyntaxError("column out of range")
        if c0 > c1:
            c0, c1 = c1, c0
        return Ref(sheet, 0, c0, MAX_ROWS - 1, c1, True, bool(ma.group(1)), True, bool(mb.group(1)), full_col=True)
    ra, rb = re.fullmatch(r"(\$?)(\d+)", a), re.fullmatch(r"(\$?)(\d+)", b)
    if ra and rb:
        r0, r1 = int(ra.group(2)) - 1, int(rb.group(2)) - 1
        if r0 < 0 or r1 < 0 or r0 >= MAX_ROWS or r1 >= MAX_ROWS:
            raise FormulaSyntaxError("row out of range")
        if r0 > r1:
            r0, r1 = r1, r0
        return Ref(sheet, r0, 0, r1, MAX_COLS - 1, bool(ra.group(1)), True, bool(rb.group(1)), True, full_row=True)
    raise FormulaSyntaxError("bad range reference")


# -- parser --------------------------------------------------------------------------------------
_BP = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5, ":": 9}
_PREFIX_BP = 7
_PERCENT_BP = 6
MAX_DEPTH = 64


class _Parser:
    def __init__(self, toks: list[Tok]) -> None:
        self.toks = toks
        self.i = 0
        self.depth = 0

    @property
    def tok(self) -> Tok:
        return self.toks[self.i]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, kind: str) -> Tok:
        if self.tok.kind != kind:
            raise FormulaSyntaxError(f"expected {kind!r} at {self.tok.pos}")
        return self.next()

    def expr(self, min_bp: int = 0) -> Node:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaSyntaxError("formula nesting too deep")
        try:
            left = self.prefix()
            while True:
                t = self.tok
                if t.kind != "op":
                    break
                if t.text == "%":
                    if _PERCENT_BP < min_bp:
                        break
                    self.next()
                    left = Percent(left)
                    continue
                bp = _BP.get(t.text)
                if bp is None or bp < min_bp:
                    break
                self.next()
                # '^' is left-associative in Excel; everything else too.
                right = self.expr(bp + 1)
                left = Binary(t.text, left, right)
            return left
        finally:
            self.depth -= 1

    def prefix(self) -> Node:
        t = self.next()
        k = t.kind
        if k == "num":
            return Num(t.value)  # type: ignore[arg-type]
        if k == "str":
            return Str(t.value)  # type: ignore[arg-type]
        if k == "bool":
            return Bool(t.value)  # type: ignore[arg-type]
        if k == "err":
            return Err(t.value)  # type: ignore[arg-type]
        if k == "ref":
            sheet, area = t.value  # type: ignore[misc]
            return make_ref(sheet, area)
        if k == "struct":
            tb, br = t.value  # type: ignore[misc]
            return parse_struct(tb, br)
        if k == "name":
            return Name(t.text)
        if k == "func":
            return self.call(t)
        if k == "op" and t.text in "+-":
            return Unary(t.text, self.expr(_PREFIX_BP))
        if k == "(":
            e = self.expr(0)
            self.expect(")")
            return e
        if k == "{":
            return self.array_literal()
        raise FormulaSyntaxError(f"unexpected {t.text!r} at {t.pos}")

    def call(self, t: Tok) -> Node:
        name = t.text.upper()
        for pre in ("_XLFN.", "_XLWS."):
            if name.startswith(pre):
                name = name[len(pre):]
        self.expect("(")
        args: list[Node] = []
        if self.tok.kind == ")":
            self.next()
            return Func(name, args)
        while True:
            if self.tok.kind in (",", ")"):
                args.append(Missing())
            else:
                args.append(self.expr(0))
            if self.tok.kind == ",":
                self.next()
                continue
            self.expect(")")
            return Func(name, args)

    def array_literal(self) -> Node:
        rows: list[list[Node]] = [[]]
        while True:
            t = self.tok
            if t.kind == "op" and t.text in "+-":
                self.next()
                inner = self.next()
                if inner.kind != "num":
                    raise FormulaSyntaxError("bad array constant")
                rows[-1].append(Num(-inner.value if t.text == "-" else inner.value))  # type: ignore[operator]
            elif t.kind in ("num", "str", "bool", "err"):
                self.next()
                rows[-1].append({"num": Num, "str": Str, "bool": Bool, "err": Err}[t.kind](t.value))  # type: ignore[operator]
            else:
                raise FormulaSyntaxError("bad array constant")
            nxt = self.next()
            if nxt.kind == ",":
                continue
            if nxt.kind == ";":
                rows.append([])
                continue
            if nxt.kind == "}":
                break
            raise FormulaSyntaxError("bad array constant")
        if len({len(r) for r in rows}) != 1:
            raise FormulaSyntaxError("array rows differ in length")
        return ArrayLit(rows)


def parse(text: str) -> Node:
    """Parse formula text (without '='). Raises FormulaSyntaxError."""
    if len(text) > 8192:
        raise FormulaSyntaxError("formula too long")
    p = _Parser(tokenize(text))
    node = p.expr(0)
    if p.tok.kind != "end":
        raise FormulaSyntaxError(f"unexpected {p.tok.text!r} at {p.tok.pos}")
    return node


def walk(node: Node):
    """Yield every node of the tree (pre-order)."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, Func):
            stack.extend(n.args)
        elif isinstance(n, Binary):
            stack.extend((n.a, n.b))
        elif isinstance(n, (Unary, Percent)):
            stack.append(n.x)
        elif isinstance(n, ArrayLit):
            for row in n.rows:
                stack.extend(row)


def translate(text: str, d_row: int, d_col: int) -> str:
    """Shift relative references by (d_row, d_col), as when a formula is copied or a shared formula
    is expanded. References pushed outside the sheet become #REF!. Strings are untouched."""
    out: list[str] = []
    last = 0
    for t in tokenize(text):
        if t.kind != "ref":
            continue
        sheet_text, area = t.value  # type: ignore[misc]
        out.append(text[last : t.pos])
        out.append((sheet_text or "") + _shift_area(area, d_row, d_col))
        last = t.end
    out.append(text[last:])
    return "".join(out)


def _shift_area(area: str, dr: int, dc: int) -> str:
    parts = area.split(":")
    shifted = [_shift_part(p, dr, dc) for p in parts]
    if any(s is None for s in shifted):
        return "#REF!"
    return ":".join(shifted)  # type: ignore[arg-type]


def _shift_part(p: str, dr: int, dc: int) -> str | None:
    m = CELL_RE.match(p)
    if m:
        ca, col, ra, row = m.group(1), m.group(2), m.group(3), int(m.group(4))
        c = col_to_index(col)
        r = row - 1
        if not ca:
            c += dc
        if not ra:
            r += dr
        if c < 0 or c >= MAX_COLS or r < 0 or r >= MAX_ROWS:
            return None
        from .refs import index_to_col

        return f"{ca}{index_to_col(c)}{ra}{r + 1}"
    m = re.fullmatch(r"(\$?)([A-Za-z]{1,3})", p)
    if m:
        if m.group(1):
            return p
        c = col_to_index(m.group(2)) + dc
        if c < 0 or c >= MAX_COLS:
            return None
        from .refs import index_to_col

        return index_to_col(c)
    m = re.fullmatch(r"(\$?)(\d+)", p)
    if m:
        if m.group(1):
            return p
        r = int(m.group(2)) - 1 + dr
        if r < 0 or r >= MAX_ROWS:
            return None
        return str(r + 1)
    return p


def substitute(node: Node, fn) -> Node:
    """Rebuild the tree with fn(leaf) applied to Ref/StructRef/Name leaves (fn returns a node)."""
    if isinstance(node, (Ref, StructRef, Name)):
        return fn(node)
    if isinstance(node, Func):
        return Func(node.name, [substitute(a, fn) for a in node.args])
    if isinstance(node, Binary):
        return Binary(node.op, substitute(node.a, fn), substitute(node.b, fn))
    if isinstance(node, Unary):
        return Unary(node.op, substitute(node.x, fn))
    if isinstance(node, Percent):
        return Percent(substitute(node.x, fn))
    if isinstance(node, ArrayLit):
        return ArrayLit([[substitute(c, fn) for c in row] for row in node.rows])
    return node
