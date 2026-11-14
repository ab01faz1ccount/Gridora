"""Encoding and delimiter detection for CSV input."""
from __future__ import annotations

import codecs
import csv
import io

from ..errors import GridoraEngineError, bad_request, import_failed

_ALLOWED = {
    "utf-8": "utf-8", "utf8": "utf-8", "utf-8-sig": "utf-8-sig",
    "utf-16": "utf-16", "utf-16-le": "utf-16-le", "utf-16-be": "utf-16-be",
    "windows-1256": "cp1256", "cp1256": "cp1256", "iso-8859-6": "iso8859-6",
    "windows-1252": "cp1252", "cp1252": "cp1252", "latin-1": "latin-1",
    "iso-8859-1": "latin-1",
}
DELIMITERS = (",", ";", "\t", "|")


def decode(data: bytes, explicit: str | None) -> tuple[str, str, bool]:
    """Returns (text, encoding_name, guessed). Only BOMs and strict UTF-8 count as certain."""
    if explicit is not None:
        name = _ALLOWED.get(explicit.strip().lower())
        if name is None:
            raise bad_request("csv.encoding_unsupported", "This text encoding is not supported.")
        try:
            return codecs.decode(data, name), name, False
        except UnicodeDecodeError:
            raise import_failed(
                "csv.decode_failed", "The file cannot be decoded with the chosen encoding."
            ) from None
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig", False
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), "utf-16", False
        except UnicodeDecodeError:
            raise import_failed("csv.decode_failed", "The file cannot be decoded.") from None
    if b"\x00" in data:
        raise GridoraEngineError(
            "unsupported_media_type", "csv.binary_content", "The file does not look like text."
        )
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    text = data.decode("cp1256", errors="replace")
    non_ascii = [ch for ch in text if ord(ch) > 127]
    arabic = sum(1 for ch in non_ascii if "\u0600" <= ch <= "\u06ff")
    if non_ascii and arabic * 2 >= len(non_ascii) and "\ufffd" not in text:
        return text, "cp1256", True
    return data.decode("cp1252", errors="replace"), "cp1252", True


def detect_delimiter(text: str) -> str:
    """Pick the candidate giving the most consistent multi-column rows in a leading sample."""
    sample = text[:200_000]
    best, best_score = ",", 0.0
    for cand in DELIMITERS:
        try:
            rows = list(csv.reader(io.StringIO(sample, newline=""), delimiter=cand))
        except csv.Error:
            continue
        if len(sample) == 200_000 and rows:
            rows = rows[:-1]  # last record may be cut mid-field
        rows = [r for r in rows[:100] if r]
        if not rows:
            continue
        counts: dict[int, int] = {}
        for r in rows:
            counts[len(r)] = counts.get(len(r), 0) + 1
        modal, freq = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
        if modal < 2:
            continue
        score = freq / len(rows) + min(modal, 10) / 1000.0
        if score > best_score + 1e-9:
            best, best_score = cand, score
    return best


def check_delimiter(delim: str) -> str:
    if len(delim) != 1 or delim in '"\r\n':
        raise bad_request("csv.delimiter_invalid", "The delimiter must be a single character.")
    return delim

