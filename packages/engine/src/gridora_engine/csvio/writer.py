"""CSV export (PLAN.md §7): UTF-8 with BOM by default, formula-injection neutralization on."""
from __future__ import annotations

import csv
import os
from pathlib import Path

from ..errors import GridoraEngineError
from ..model.sheet import SheetStore
from ..model.values import BOOL, ERR, ERR_CODES, NUM, STR, StringTable

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def format_number(v: float) -> str:
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def write_csv(
    path: Path, store: SheetStore, strings: StringTable, encoding: str, neutralize: bool
) -> int:
    """Write the sheet; returns the number of neutralized text cells."""
    rows, cols = store.used_size()
    neutralized = 0
    tmp = path.with_name(path.name + ".part")
    try:
        with open(tmp, "w", encoding=encoding, newline="", errors="strict") as f:
            w = csv.writer(f, delimiter=",", lineterminator="\r\n")
            for first, chunks in store.row_blocks(cols):
                last = min(first + 256, rows)
                for r in range(first, last):
                    i = r - first
                    out: list[str] = []
                    for ch in chunks:
                        if ch is None:
                            out.append("")
                            continue
                        tag = ch.tags[i]
                        if tag == 0:
                            out.append("")
                        elif tag == NUM:
                            out.append(format_number(ch.vals[i]))
                        elif tag == STR:
                            s = strings.get(int(ch.vals[i]))
                            if neutralize and s.startswith(_DANGEROUS):
                                s = "'" + s
                                neutralized += 1
                            out.append(s)
                        elif tag == BOOL:
                            out.append("TRUE" if ch.vals[i] else "FALSE")
                        elif tag == ERR:
                            out.append(ERR_CODES[int(ch.vals[i])])
                    w.writerow(out)
        os.replace(tmp, path)
    except UnicodeEncodeError:
        tmp.unlink(missing_ok=True)
        raise GridoraEngineError(
            "validation_failed", "csv.unencodable_character",
            "The sheet contains characters that the chosen CSV encoding cannot represent.",
        ) from None
    except OSError:
        tmp.unlink(missing_ok=True)
        raise GridoraEngineError(
            "internal_error", "io.write_failed", "The file could not be written."
        ) from None
    return neutralized
