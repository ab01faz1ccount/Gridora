"""Streaming multipart upload with hard limits. The body is never buffered in memory.

Limits are enforced while streaming: the moment the file part passes max_bytes the upload is
aborted with 413 and the quarantine file removed. Content-Length is only an early hint.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool

from ..core.errors import DomainError
from ..storage.layout import StorageLayout

ALLOWED = {"xlsx": "xlsx", "xlsm": "xlsm", "csv": "csv"}
ZIP_MAGIC = b"PK\x03\x04"
OVERHEAD = 64 * 1024  # multipart framing allowance on top of the file limit


@dataclass(frozen=True)
class StoredUpload:
    quarantine: Path
    display_name: str
    ext: str
    size: int
    sha256: str


def clean_display_name(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip(" .")
    return name[:255] or "file"


def extension_of(display_name: str) -> str | None:
    if "." not in display_name:
        return None
    return ALLOWED.get(display_name.rsplit(".", 1)[-1].lower())


def check_magic(path: Path, ext: str) -> None:
    head = path.read_bytes()[:8192] if path.stat().st_size else b""
    if not head:
        raise DomainError("unsupported_media_type", "The file is empty.")
    if ext in ("xlsx", "xlsm"):
        if not head.startswith(ZIP_MAGIC):
            raise DomainError("unsupported_media_type", "The file is not a valid workbook.")
    elif b"\x00" in head:  # CSV must be text (UTF-8 / Windows-1256); UTF-16 etc. is refused
        raise DomainError("unsupported_media_type", "The file is not a text CSV file.")


class _Collector:
    """Typed state for one multipart parse; callbacks run in a worker thread."""

    def __init__(self, fh: BinaryIO, max_bytes: int) -> None:
        self.fh, self.max_bytes = fh, max_bytes
        self.sha = hashlib.sha256()
        self.size = 0
        self.parts = 0
        self.in_file = False
        self.finished = False  # closing boundary seen: a truncated body is NOT a valid upload
        self.filename: str | None = None
        self._name: bytes | None = None
        self._field = b""
        self._value = b""

    def on_part_begin(self) -> None:
        self.parts += 1
        self._name, self.filename = None, None
        self._field = self._value = b""

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]

    def on_header_end(self) -> None:
        if self._field.lower() == b"content-disposition":
            _, opts = parse_options_header(self._value)
            self._name = opts.get(b"name")
            fn = opts.get(b"filename")
            self.filename = fn.decode("utf-8", "replace") if fn else None
        self._field = self._value = b""

    def on_headers_finished(self) -> None:
        if self._name != b"file" or self.filename is None or self.parts != 1:
            raise DomainError("bad_request", "Send exactly one file field named 'file'.")
        self.in_file = True

    def on_end(self) -> None:
        self.finished = True

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        self.size += len(chunk)
        if self.size > self.max_bytes:
            raise DomainError("file_too_large")
        self.sha.update(chunk)
        self.fh.write(chunk)


async def receive_upload(
    stream: AsyncIterator[bytes],
    content_type: str,
    content_length: int | None,
    layout: StorageLayout,
    max_bytes: int,
) -> StoredUpload:
    ctype, params = parse_options_header(content_type)
    if ctype != b"multipart/form-data" or b"boundary" not in params:
        raise DomainError("unsupported_media_type", "Expected multipart/form-data.")
    if content_length is not None and content_length > max_bytes + OVERHEAD:
        raise DomainError("file_too_large")

    qpath = layout.quarantine_path(uuid.uuid4())
    qpath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fh = open(qpath, "wb")  # noqa: SIM115, ASYNC230 - quick open; closed below
    col = _Collector(fh, max_bytes)
    parser = MultipartParser(
        params[b"boundary"],
        callbacks={
            "on_part_begin": col.on_part_begin,
            "on_header_field": col.on_header_field,
            "on_header_value": col.on_header_value,
            "on_header_end": col.on_header_end,
            "on_headers_finished": col.on_headers_finished,
            "on_part_data": col.on_part_data,
            "on_end": col.on_end,
        },
        max_size=max_bytes + OVERHEAD,
    )
    received = 0
    try:
        async for chunk in stream:
            received += len(chunk)
            if received > max_bytes + OVERHEAD:
                raise DomainError("file_too_large")
            await run_in_threadpool(parser.write, chunk)  # disk writes stay off the event loop
        parser.finalize()
        fh.close()
        if not col.finished:
            raise DomainError("bad_request", "The upload was incomplete.")
        if not col.in_file:
            raise DomainError("bad_request", "Send exactly one file field named 'file'.")
        display = clean_display_name(col.filename)
        ext = extension_of(display)
        if ext is None:
            raise DomainError("unsupported_media_type", "Only .xlsx, .xlsm and .csv are supported.")
        check_magic(qpath, ext)
        return StoredUpload(qpath, display, ext, col.size, col.sha.hexdigest())
    except DomainError:
        _discard(fh, qpath)
        raise
    except Exception as exc:  # malformed multipart, I/O errors, client abort
        _discard(fh, qpath)
        raise DomainError("bad_request", "The upload could not be read.") from exc


def _discard(fh: BinaryIO, path: Path) -> None:
    try:
        fh.close()
    finally:
        path.unlink(missing_ok=True)
