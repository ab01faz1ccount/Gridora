"""Cell formats: read the look of each xf, make new ones, and write them back into styles.xml.

Imported workbooks keep their styles.xml byte for byte until a format is changed; then only the
sections `numFmts`, `fonts`, `fills` and `cellXfs` get new entries appended (existing entries and
their ids never move). A format made at run time is a *derived* xf: a copy of an imported xf
(`root`) with some properties changed, so borders, protection and anything else we do not model
are inherited from the root.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from ..errors import unsupported_workbook, validation_failed
from ..model.dates import is_date_format
from ..model.workbook import Derived, Props, StyleInfo

BUILTIN_CODES = {
    1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00",
    12: "# ?/?", 13: "# ??/??", 14: "mm-dd-yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy",
    18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy hh:mm",
    37: "#,##0 ;(#,##0)", 38: "#,##0 ;[Red](#,##0)", 39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)", 45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0", 49: "@",
}
_CODE_IDS = {v: k for k, v in BUILTIN_CODES.items() if k not in (14, 49)}
_CODE_IDS["yyyy-mm-dd"] = 14  # shown with the locale's date order; the grid shows dates by calendar anyway
MAX_XFS = 65535

BASE_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
)

_ATTR = re.compile(r'([\w:.-]+)\s*=\s*"([^"]*)"')


def _section(data: bytes, name: str) -> re.Match[bytes] | None:
    return re.search(rb"<%b\b([^>]*?)(?:/>|>(.*?)</%b>)" % (name.encode(), name.encode()), data, re.DOTALL)


def _items(body: bytes | None, tag: str) -> list[bytes]:
    if not body:
        return []
    t = tag.encode()
    return re.findall(rb"<%b\b[^>]*?/>|<%b\b[^>]*?>.*?</%b>" % (t, t, t), body, re.DOTALL)


def _attrs(raw: bytes) -> dict[str, str]:
    head = re.match(rb"<[\w:]+\b([^>]*?)/?>", raw, re.DOTALL)
    return dict(_ATTR.findall(head.group(1).decode("utf-8", "replace"))) if head else {}


def _child_attrs(raw: bytes) -> dict[str, dict[str, str]]:
    """Children of a font/fill/xf by tag name -> attributes (they are all empty elements)."""
    out: dict[str, dict[str, str]] = {}
    head = re.match(rb"<[\w:]+\b[^>]*?(/?)>", raw, re.DOTALL)
    if head is None or head.group(1) == b"/":
        return out
    inner = raw[head.end():]
    for m in re.finditer(rb"<([\w:]+)\b([^>]*?)/?>", inner):
        out.setdefault(m.group(1).decode(), dict(_ATTR.findall(m.group(2).decode("utf-8", "replace"))))
    return out


def _rgb(attrs: dict[str, str]) -> str | None:
    v = attrs.get("rgb")
    return "#" + v[-6:].upper() if v and re.fullmatch(r"[0-9A-Fa-f]{6,8}", v) else None


def _font_props(raw: bytes) -> dict[str, Any]:
    ch = _child_attrs(raw)

    def on(tag: str) -> bool:
        return tag in ch and ch[tag].get("val", "1") not in ("0", "false")

    u = ch.get("u")
    try:
        size = float(ch["sz"]["val"]) if "sz" in ch else None
    except (KeyError, ValueError):
        size = None
    return {
        "bold": on("b"), "italic": on("i"), "underline": u is not None and u.get("val", "single") != "none", "strike": on("strike"),
        "font_name": ch.get("name", {}).get("val"), "font_size": size, "font_color": _rgb(ch.get("color", {})),
    }


def _fill_color(raw: bytes) -> str | None:
    ch = _child_attrs(raw)
    pf = re.search(rb"patternType=\"(\w+)\"", raw)
    if pf is None or pf.group(1) != b"solid":
        return None
    return _rgb(ch.get("fgColor", {}))


def _split(data: bytes) -> dict[str, Any] | None:
    """Sections of styles.xml we need, or None when the file is laid out in a way we do not patch."""
    if re.search(rb"<\w+:styleSheet\b", data):
        return None
    out: dict[str, Any] = {}
    for name, item in (("fonts", "font"), ("fills", "fill"), ("cellXfs", "xf")):
        m = _section(data, name)
        if m is None:
            return None
        out[name] = (m, _items(m.group(2), item))
    out["numFmts"] = _section(data, "numFmts")
    return out


def read_book(data: bytes, table: StyleInfo) -> None:
    """Fill table.props (and codes) from styles.xml; leaves props None when it cannot be read."""
    sec = _split(data)
    if sec is None:
        return
    nf = sec["numFmts"]
    if nf is not None:
        for raw in _items(nf.group(2), "numFmt"):
            a = _attrs(raw)
            if a.get("numFmtId", "").isdigit():
                table.codes[int(a["numFmtId"])] = _unescape(a.get("formatCode", ""))
    fonts = [_font_props(r) for r in sec["fonts"][1]]
    fills = [_fill_color(r) for r in sec["fills"][1]]
    out: list[Props] = []
    for raw in sec["cellXfs"][1]:
        a = _attrs(raw)
        ch = _child_attrs(raw)
        fid = int(a["numFmtId"]) if a.get("numFmtId", "0").isdigit() else 0
        code = table.codes.get(fid) or BUILTIN_CODES.get(fid)
        font = fonts[int(a["fontId"])] if a.get("fontId", "").isdigit() and int(a["fontId"]) < len(fonts) else {}
        fill = fills[int(a["fillId"])] if a.get("fillId", "").isdigit() and int(a["fillId"]) < len(fills) else None
        al = ch.get("alignment", {})
        h = al.get("horizontal")
        out.append(Props(
            number_format=None if code in (None, "General") else code, fill_color=fill,
            halign=h if h in ("left", "center", "right", "justify") else None,
            wrap=al.get("wrapText", "0") in ("1", "true"), **font,
        ))
    if len(out) == len(table.xf_numfmt):
        table.props = out


def _unescape(s: str) -> str:
    return s.replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def default_table() -> StyleInfo:
    """The formats of a workbook that has no styles.xml of its own (CSV): one default format."""
    t = StyleInfo(xf_numfmt=[0], xf_is_date=[False], xf_code=[None], props=[Props(font_name="Calibri", font_size=11.0)], n_imported=1)
    return t


def props_of(table: StyleInfo, xf: int) -> Props:
    if xf < table.n_imported:
        if table.props is None:
            raise unsupported_workbook("format.styles_not_readable", "This workbook's cell formats cannot be changed safely.")
        return table.props[xf] if xf < len(table.props) else Props()
    return table.derived[xf - table.n_imported].props


def _root(table: StyleInfo, xf: int) -> int:
    return xf if xf < table.n_imported else table.derived[xf - table.n_imported].root


def derive(table: StyleInfo, base: int, change: dict[str, Any]) -> int:
    """The xf id for `base` with `change` applied (an existing one when the result already exists)."""
    cur = props_of(table, base)
    new = replace(cur, **change)
    if new == cur:
        return base
    root = _root(table, base)
    for i, d in enumerate(table.derived):
        if d.root == root and d.props == new and not d.placeholder:
            return table.n_imported + i
    if len(table.xf_numfmt) >= MAX_XFS:
        raise validation_failed("format.too_many_styles", "The workbook has too many cell formats.")
    code = new.number_format
    fid = number_format_id(table, code)
    table.derived.append(Derived(root, new))
    table.xf_numfmt.append(fid)
    table.xf_code.append(None if code in (None, "General") else code)
    table.xf_is_date.append(is_date_format(code, fid))
    return len(table.xf_numfmt) - 1


def number_format_id(table: StyleInfo, code: str | None) -> int:
    if code in (None, "", "General"):
        return 0
    if code in _CODE_IDS:
        return _CODE_IDS[code]
    for k, v in table.codes.items():
        if v == code:
            return k
    k = max([163, *table.codes]) + 1
    table.codes[k] = code
    table.new_codes[k] = code
    return k


def ensure_derived(table: StyleInfo, specs: list[tuple[int, int, Props]]) -> None:
    """Make sure ids from a replayed delta exist: (id, root, props). Gaps become placeholders."""
    for xf, root, props in sorted(specs, key=lambda s: s[0]):
        if xf < table.n_imported:
            continue
        i = xf - table.n_imported
        code = props.number_format
        if i < len(table.derived) and not table.derived[i].placeholder:
            continue
        if i > len(table.derived) + MAX_XFS or xf >= MAX_XFS:
            raise validation_failed("delta.out_of_range", "The change refers to a cell format that does not exist.")
        while len(table.derived) < i:
            table.derived.append(Derived(0, props_of(table, 0), placeholder=True))
            table.xf_numfmt.append(0)
            table.xf_code.append(None)
            table.xf_is_date.append(False)
        fid = number_format_id(table, code)
        entry = Derived(root, props)
        if i < len(table.derived):
            table.derived[i] = entry
            table.xf_numfmt[xf], table.xf_code[xf], table.xf_is_date[xf] = fid, (None if code in (None, "General") else code), is_date_format(code, fid)
        else:
            table.derived.append(entry)
            table.xf_numfmt.append(fid)
            table.xf_code.append(None if code in (None, "General") else code)
            table.xf_is_date.append(is_date_format(code, fid))


# ------------------------------------------------------------------ writing ----
def _set_attr(tag: bytes, name: str, value: str) -> bytes:
    n = name.encode()
    v = value.encode()
    pat = re.compile(rb'(\s%b\s*=\s*)"[^"]*"' % n)
    if pat.search(tag):
        return pat.sub(lambda m: m.group(1) + b'"' + v + b'"', tag, count=1)
    m = re.match(rb"<[\w:]+", tag)
    assert m
    return tag[: m.end()] + b" " + n + b'="' + v + b'"' + tag[m.end():]


def _font_xml(raw: bytes | None, p: Props) -> bytes:
    ch = _child_attrs(raw) if raw else {}
    parts: list[bytes] = []
    if p.bold:
        parts.append(b"<b/>")
    if p.italic:
        parts.append(b"<i/>")
    if p.strike:
        parts.append(b"<strike/>")
    if p.underline:
        parts.append(b"<u/>")
    size = p.font_size if p.font_size is not None else (float(ch["sz"]["val"]) if "sz" in ch and "val" in ch["sz"] else 11.0)
    parts.append(b'<sz val="%s"/>' % (f"{size:g}").encode())
    if p.font_color:
        parts.append(b'<color rgb="FF%s"/>' % p.font_color[1:].encode())
    elif "color" in ch:
        parts.append(b"<color " + " ".join(f'{k}="{v}"' for k, v in ch["color"].items()).encode() + b"/>")
    name = p.font_name or ch.get("name", {}).get("val") or "Calibri"
    parts.append(b'<name val="%s"/>' % _escape(name).encode())
    for extra in ("family", "charset"):
        if extra in ch:
            parts.append(b"<" + extra.encode() + b' val="' + ch[extra].get("val", "").encode() + b'"/>')
    return b"<font>" + b"".join(parts) + b"</font>"


def _fill_xml(color: str) -> bytes:
    return (b'<fill><patternFill patternType="solid"><fgColor rgb="FF%s"/><bgColor indexed="64"/></patternFill></fill>' % color[1:].encode())


def _alignment(raw: bytes, p: Props) -> bytes:
    cur = _child_attrs(raw).get("alignment", {})
    cur = {k: v for k, v in cur.items() if k not in ("horizontal", "wrapText")}
    if p.halign:
        cur["horizontal"] = p.halign
    if p.wrap:
        cur["wrapText"] = "1"
    return b"<alignment " + " ".join(f'{k}="{v}"' for k, v in cur.items()).encode() + b"/>" if cur else b""


def _xf_xml(raw: bytes, root: Props, p: Props, ids: dict[str, int]) -> bytes:
    head = re.match(rb"<xf\b[^>]*?>|<xf\b[^>]*?/>", raw, re.DOTALL)
    assert head
    tag = head.group(0)
    selfclosed = tag.endswith(b"/>")
    tag = tag[:-2] + b">" if selfclosed else tag
    body = b"" if selfclosed else re.sub(rb"</xf>\s*$", b"", raw[head.end():])
    for k, v in ids.items():
        tag = _set_attr(tag, k, str(v))
    for flag in ("applyNumberFormat", "applyFont", "applyFill"):
        tag = _set_attr(tag, flag, "1")
    if (p.halign, p.wrap) != (root.halign, root.wrap):
        body = re.sub(rb"<alignment\b[^>]*?(?:/>|>.*?</alignment>)", b"", body, flags=re.DOTALL)
        tag = _set_attr(tag, "applyAlignment", "1")
        body = _alignment(raw, p) + body
    return tag + body + b"</xf>" if body else tag[:-1] + b"/>"


def patch_styles(data: bytes, table: StyleInfo) -> bytes:
    """styles.xml with the run-time formats appended; the input unchanged when there are none."""
    if not table.derived and not table.new_codes:
        return data
    sec = _split(data)
    if sec is None or table.props is None:
        raise unsupported_workbook("export.styles_not_patchable", "This workbook's cell formats cannot be exported with changes yet.")
    font_m, fonts = sec["fonts"]
    fill_m, fills = sec["fills"]
    xf_m, xfs = sec["cellXfs"]
    new_fonts: list[bytes] = []
    new_fills: list[bytes] = []
    new_xfs: list[bytes] = []
    xf_attrs = [_attrs(x) for x in xfs]
    for d in table.derived:
        root = d.root
        rp = table.props[root] if root < len(table.props) else Props()
        a = xf_attrs[root] if root < len(xf_attrs) else {}
        p = d.props
        font_id = int(a["fontId"]) if a.get("fontId", "").isdigit() else 0
        fill_id = int(a["fillId"]) if a.get("fillId", "").isdigit() else 0
        if (p.bold, p.italic, p.underline, p.strike, p.font_name, p.font_size, p.font_color) != (rp.bold, rp.italic, rp.underline, rp.strike, rp.font_name, rp.font_size, rp.font_color):
            fx = _font_xml(fonts[font_id] if font_id < len(fonts) else None, p)
            if fx not in new_fonts:
                new_fonts.append(fx)
            font_id = len(fonts) + new_fonts.index(fx)
        if p.fill_color != rp.fill_color:
            if p.fill_color is None:
                fill_id = 0
            else:
                lx = _fill_xml(p.fill_color)
                if lx not in new_fills:
                    new_fills.append(lx)
                fill_id = len(fills) + new_fills.index(lx)
        fmt_id = number_format_id(table, p.number_format)
        raw = xfs[root] if root < len(xfs) else b'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        new_xfs.append(_xf_xml(raw, rp, p, {"numFmtId": fmt_id, "fontId": font_id, "fillId": fill_id}))
    edits: list[tuple[int, int, bytes]] = []

    def grown(m: re.Match[bytes], items: list[bytes], added: list[bytes], tag: str) -> tuple[int, int, bytes]:
        open_tag = re.match(rb"<\w+\b[^>]*?>", m.group(0))
        assert open_tag
        ot = open_tag.group(0)
        if ot.endswith(b"/>"):
            ot = ot[:-2] + b">"
        ot = _set_attr(ot, "count", str(len(items) + len(added)))
        return m.start(), m.end(), ot + (m.group(2) or b"") + b"".join(added) + b"</" + tag.encode() + b">"

    if new_fonts:
        edits.append(grown(font_m, fonts, new_fonts, "fonts"))
    if new_fills:
        edits.append(grown(fill_m, fills, new_fills, "fills"))
    edits.append(grown(xf_m, xfs, new_xfs, "cellXfs"))
    if table.new_codes:
        add = [b'<numFmt numFmtId="%d" formatCode="%b"/>' % (k, _escape(v).encode()) for k, v in sorted(table.new_codes.items())]
        nm = sec["numFmts"]
        if nm is not None:
            edits.append(grown(nm, _items(nm.group(2), "numFmt"), add, "numFmts"))
        else:
            at = font_m.start()
            edits.append((at, at, b'<numFmts count="%d">' % len(add) + b"".join(add) + b"</numFmts>"))
    out = data
    for s, e, text in sorted(edits, key=lambda x: -x[0]):
        out = out[:s] + text + out[e:]
    return out
