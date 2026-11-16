"""Independent facts about a worksheet package, computed WITHOUT the engine's reader
(zipfile + ElementTree), used as the oracle in corpus tests. Corpus files are trusted fixtures."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def cell_facts(path: Path) -> tuple[int, int]:
    """(cells with a value, formula or inline text; of which error cells) over all worksheet parts."""
    n = errs = 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not (name.startswith("xl/worksheets/sheet") and name.endswith(".xml")):
                continue
            with z.open(name) as f:
                for _ev, el in ET.iterparse(f, events=("end",)):
                    if el.tag == MAIN + "c":
                        if any(el.find(MAIN + t) is not None for t in ("v", "f", "is")):
                            n += 1
                            errs += el.get("t") == "e"
                        el.clear()
    return n, errs


def part_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def defined_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
    return re.findall(r'<definedName[^>]*\bname="([^"]*)"', wb)
