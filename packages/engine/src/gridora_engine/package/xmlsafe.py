"""Hostile-safe XML parsing on top of expat (PLAN.md section 10).

Rules: UTF-8 only; no DOCTYPE, entity declarations, external entities or parameter entities;
depth cap; every failure becomes a typed engine error with a fixed message (never the
parser's text, which could echo input). Events use "namespace-uri local" names.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import NoReturn
from xml.parsers import expat

from ..errors import import_failed
from ..limits import Deadline

StartFn = Callable[[str, dict[str, str]], None]
EndFn = Callable[[str], None]
CharsFn = Callable[[str], None]

_DECL = re.compile(rb"""^(?:\xef\xbb\xbf)?\s*<\?xml[^>]*?encoding\s*=\s*["']([^"']+)["']""")
CHUNK = 1 << 20


class _Forbidden(Exception):
    pass


def local(name: str) -> str:
    """Local part of an event name ('uri local' -> 'local')."""
    return name.rsplit(" ", 1)[-1]


def check_encoding(head: bytes) -> None:
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or head[:4] in (b"<\x00?\x00", b"\x00<\x00?"):
        raise import_failed("xml.encoding_unsupported", "An XML part uses an unsupported encoding.")
    m = _DECL.match(head[:512])
    if m and m.group(1).strip().lower() not in (b"utf-8", b"utf8"):
        raise import_failed("xml.encoding_unsupported", "An XML part uses an unsupported encoding.")


def parse(
    data: bytes,
    *,
    start: StartFn | None = None,
    end: EndFn | None = None,
    chars: CharsFn | None = None,
    max_depth: int = 64,
    deadline: Deadline | None = None,
) -> None:
    """Parse `data`, calling the handlers. Raises GridoraEngineError on any problem."""
    check_encoding(data[:600])
    depth = 0

    def forbid(*_a: object) -> NoReturn:
        raise _Forbidden

    def on_start(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth
        depth += 1
        if depth > max_depth:
            raise _Forbidden
        if start is not None:
            start(name, attrs)

    def on_end(name: str) -> None:
        nonlocal depth
        depth -= 1
        if end is not None:
            end(name)

    p = expat.ParserCreate(namespace_separator=" ")
    p.buffer_text = True
    p.StartDoctypeDeclHandler = forbid
    p.EntityDeclHandler = forbid
    p.NotationDeclHandler = forbid
    p.ExternalEntityRefHandler = forbid
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    p.StartElementHandler = on_start
    p.EndElementHandler = on_end
    if chars is not None:
        p.CharacterDataHandler = chars
    try:
        for i in range(0, len(data), CHUNK):
            p.Parse(data[i : i + CHUNK], False)
            if deadline is not None:
                deadline.check()
        p.Parse(b"", True)
    except _Forbidden:
        raise import_failed(
            "xml.forbidden_construct",
            "An XML part contains a construct that is not allowed (DOCTYPE, entity or excessive depth).",
        ) from None
    except expat.ExpatError:
        raise import_failed("xml.malformed", "An XML part is not well-formed.") from None
