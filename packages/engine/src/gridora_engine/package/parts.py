"""OPC package model: ordered parts, content types, relationships (PLAN.md section 5).

Only `[Content_Types].xml` and `.rels` parts are parsed here. Every other part is opaque bytes
that stay in the source archive until written (state "clean") - this is what makes unknown
parts byte-for-byte preserved. External relationship targets are recorded, never followed.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self

from ..errors import import_failed, unsupported_workbook
from ..limits import Deadline, ResourceLimits
from . import xmlsafe
from .zipin import SafeZip

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOC_REL = "officeDocument"
WORKBOOK_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": "xlsx",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml": "xlsm",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml": "xltx",
    "application/vnd.ms-excel.template.macroEnabled.main+xml": "xltm",
}
CONTENT_TYPES = "[Content_Types].xml"
PartState = Literal["clean", "dirty", "dropped", "added"]


@dataclass
class Relationship:
    id: str
    type: str
    target: str
    external: bool = False


@dataclass
class Part:
    name: str
    state: PartState = "clean"
    data: bytes | None = None  # only for dirty/added parts; clean parts stream from the source


@dataclass
class ContentTypes:
    defaults: dict[str, str] = field(default_factory=dict)  # lower-case extension -> type
    overrides: dict[str, str] = field(default_factory=dict)  # lower-case part name -> type

    def of(self, part_name: str) -> str | None:
        hit = self.overrides.get(part_name.lower())
        if hit is not None:
            return hit
        ext = part_name.rsplit(".", 1)[-1].lower() if "." in part_name else ""
        return self.defaults.get(ext)


def rels_name_for(part: str) -> str:
    d, base = posixpath.split(part)
    return posixpath.join(d, "_rels", base + ".rels")


def resolve_target(source_part: str, target: str) -> str:
    """OPC target resolution; raises if the result would leave the package."""
    if target.startswith("/"):
        norm = posixpath.normpath(target[1:])
    else:
        base = posixpath.dirname(source_part)
        norm = posixpath.normpath(posixpath.join(base, target))
    if norm.startswith(("..", "/")) or norm in (".", ""):
        raise import_failed("package.relationship_escape", "A relationship points outside the package.")
    return norm


class PackageModel:
    def __init__(self, zin: SafeZip) -> None:
        self.zin = zin
        self.parts: list[Part] = [Part(n) for n in zin.names()]
        self.by_name: dict[str, Part] = {p.name: p for p in self.parts}
        self._folded: dict[str, str] = {p.name.casefold(): p.name for p in self.parts}
        self.content_types = ContentTypes()
        self.workbook_part: str = ""
        self.kind: str = ""  # xlsx | xlsm | xltx | xltm

    @classmethod
    def open(
        cls, path: Path, limits: ResourceLimits, deadline: Deadline | None = None
    ) -> PackageModel:
        zin = SafeZip(path, limits, deadline)
        try:
            model = cls(zin)
            model._load_structure()
        except BaseException:
            zin.close()
            raise
        return model

    def close(self) -> None:
        self.zin.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a: object) -> None:
        self.close()

    # -- structure -----------------------------------------------------------------------------
    def has(self, name: str) -> bool:
        return name.casefold() in self._folded

    def actual_name(self, name: str) -> str | None:
        return self._folded.get(name.casefold())

    def read(self, name: str) -> bytes:
        part = self.by_name[name]
        if part.data is not None:
            return part.data
        return self.zin.read(name)

    def _load_structure(self) -> None:
        if CONTENT_TYPES not in self.by_name:
            raise unsupported_workbook(
                "package.no_content_types", "The package has no content types part."
            )
        self.content_types = self._parse_content_types(self.zin.read(CONTENT_TYPES))
        root = self.relationships("")
        doc = [r for r in root if r.type.rsplit("/", 1)[-1] == OFFICE_DOC_REL and not r.external]
        if len(doc) != 1:
            raise unsupported_workbook(
                "package.no_main_document", "The package does not have exactly one main document."
            )
        wb = self.actual_name(resolve_target("", doc[0].target))
        if wb is None:
            raise unsupported_workbook("package.no_main_document", "The main document part is missing.")
        kind = WORKBOOK_TYPES.get(self.content_types.of(wb) or "")
        if kind is None:
            raise unsupported_workbook(
                "package.not_a_workbook", "The package is not a spreadsheet workbook."
            )
        self.workbook_part, self.kind = wb, kind

    def _parse_content_types(self, data: bytes) -> ContentTypes:
        ct = ContentTypes()

        def start(name: str, attrs: dict[str, str]) -> None:
            if name == f"{CT_NS} Default" and "Extension" in attrs and "ContentType" in attrs:
                ct.defaults[attrs["Extension"].lower()] = attrs["ContentType"]
            elif name == f"{CT_NS} Override" and "PartName" in attrs and "ContentType" in attrs:
                ct.overrides[attrs["PartName"].lstrip("/").lower()] = attrs["ContentType"]

        xmlsafe.parse(data, start=start, max_depth=self.zin.limits.max_xml_depth, deadline=self.zin.deadline)
        return ct

    def relationships(self, source_part: str) -> list[Relationship]:
        """Relationships of a part ('' = package root). Missing .rels means none."""
        rname = "_rels/.rels" if source_part == "" else rels_name_for(source_part)
        actual = self.actual_name(rname)
        if actual is None:
            return []
        out: list[Relationship] = []

        def start(name: str, attrs: dict[str, str]) -> None:
            if name == f"{REL_NS} Relationship" and "Id" in attrs and "Type" in attrs and "Target" in attrs:
                out.append(
                    Relationship(
                        attrs["Id"], attrs["Type"], attrs["Target"],
                        external=attrs.get("TargetMode", "Internal") == "External",
                    )
                )

        xmlsafe.parse(
            self.read(actual), start=start, max_depth=self.zin.limits.max_xml_depth,
            deadline=self.zin.deadline,
        )
        return out
