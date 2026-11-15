"""Hostile-safe ZIP reader (PLAN.md section 10).

Validated BEFORE any decompression: entry count (from the end-of-central-directory record,
before zipfile builds its table), names, flags, compression methods, declared sizes and ratios,
local-header consistency and overlapping entries. During reads, bytes actually produced are
counted against per-part and total budgets; declared sizes are never trusted. Names are only
dictionary keys: nothing is ever extracted to disk.
"""
from __future__ import annotations

import contextlib
import itertools
import re
import struct
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Self

from ..errors import file_too_large, import_failed, unsupported_workbook
from ..limits import Deadline, ResourceLimits

_EOCD = b"PK\x05\x06"
_EOCD64_LOC = b"PK\x06\x07"
_EOCD64 = b"PK\x06\x06"
_LOCAL = b"PK\x03\x04"
_RATIO_MIN_BYTES = 1 << 20  # the ratio check only applies to entries above 1 MiB
_READ = 64 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:")
_ALLOWED_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


def _corrupt() -> Exception:
    return import_failed("zip.corrupt", "The file is not a valid ZIP package.")


def declared_entry_count(f: BinaryIO, size: int) -> int:
    """Entry count from the EOCD record (zip64 aware), read without building any table."""
    tail_len = min(size, 65557)
    f.seek(size - tail_len)
    tail = f.read(tail_len)
    i = tail.rfind(_EOCD)
    if i < 0 or len(tail) - i < 22:
        raise _corrupt()
    total = int(struct.unpack_from("<H", tail, i + 10)[0])
    if total == 0xFFFF:
        j = i - 20
        if j >= 0 and tail[j : j + 4] == _EOCD64_LOC:
            off64 = int(struct.unpack_from("<Q", tail, j + 8)[0])
            if 0 <= off64 < size:
                f.seek(off64)
                rec = f.read(56)
                if len(rec) >= 56 and rec[:4] == _EOCD64:
                    total = int(struct.unpack_from("<Q", rec, 32)[0])
    return total


def check_name(name: str) -> None:
    bad = (
        not name
        or name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or _DRIVE.match(name) is not None
        or any(ord(c) < 32 for c in name)
        or len(name) > 512
    )
    if not bad:
        segs = name.split("/")
        if name.endswith("/"):
            segs = segs[:-1]
        bad = any(s in ("", ".", "..") for s in segs)
    if bad:
        raise unsupported_workbook(
            "zip.path_traversal", "The package contains an entry with an unsafe name."
        )


class SafeZip:
    """Open, validate and read a ZIP package. Use as a context manager."""

    def __init__(
        self, path: Path, limits: ResourceLimits, deadline: Deadline | None = None
    ) -> None:
        self.limits = limits
        self.deadline = deadline or Deadline(None)
        self.total_read = 0
        try:
            self._f: BinaryIO = open(path, "rb")  # noqa: SIM115 (closed in close())
        except OSError:
            raise import_failed("io.read_failed", "The file could not be read.") from None
        try:
            self._init()
        except BaseException:
            self._f.close()
            raise

    def _init(self) -> None:
        f, limits = self._f, self.limits
        f.seek(0, 2)
        self.size = f.tell()
        if self.size > limits.max_file_bytes:
            raise file_too_large("limits.file_too_large", "The file is larger than allowed.")
        f.seek(0)
        head = f.read(4)
        if head[:4] == b"\xd0\xcf\x11\xe0":
            raise unsupported_workbook(
                "xlsx.encrypted_or_legacy",
                "The file is an encrypted or legacy (OLE2) workbook, which is not supported.",
            )
        if head[:2] != b"PK":
            raise unsupported_workbook("zip.not_a_zip", "The file is not an XLSX package.")
        if declared_entry_count(f, self.size) > limits.max_zip_entries:
            raise unsupported_workbook(
                "zip.too_many_entries", "The package contains more entries than allowed."
            )
        try:
            self._zf = zipfile.ZipFile(f)
            infos = self._zf.infolist()
        except (zipfile.BadZipFile, ValueError, OSError, EOFError, struct.error, zlib.error):
            raise _corrupt() from None
        if len(infos) > limits.max_zip_entries:
            raise unsupported_workbook(
                "zip.too_many_entries", "The package contains more entries than allowed."
            )
        self._validate(infos)
        self.infos = [i for i in infos if not i.filename.endswith("/")]
        self.by_name = {i.filename: i for i in self.infos}

    def _validate(self, infos: list[zipfile.ZipInfo]) -> None:
        limits = self.limits
        seen: set[str] = set()
        declared_total = 0
        spans: list[tuple[int, int, zipfile.ZipInfo]] = []
        for info in infos:
            check_name(info.orig_filename)
            folded = info.filename.casefold()
            if folded in seen:
                raise unsupported_workbook(
                    "zip.duplicate_name", "The package contains duplicate entry names."
                )
            seen.add(folded)
            if info.flag_bits & 0x1 or info.flag_bits & 0x40 or info.flag_bits & 0x2000:
                raise unsupported_workbook(
                    "zip.encrypted", "The package contains encrypted entries."
                )
            if info.compress_type not in _ALLOWED_METHODS:
                raise unsupported_workbook(
                    "zip.method_unsupported", "The package uses an unsupported compression method."
                )
            if info.file_size > limits.max_part_bytes:
                raise unsupported_workbook(
                    "zip.part_too_large", "A package entry is larger than allowed."
                )
            declared_total += info.file_size
            if declared_total > limits.max_uncompressed_bytes:
                raise unsupported_workbook(
                    "zip.uncompressed_too_large",
                    "The package would expand to more than the allowed size.",
                )
            if (
                info.file_size > _RATIO_MIN_BYTES
                and info.file_size > limits.max_compression_ratio * max(info.compress_size, 1)
            ):
                raise unsupported_workbook(
                    "zip.ratio_exceeded", "A package entry has a suspicious compression ratio."
                )
            start = self._data_start(info)
            end = start + info.compress_size
            if end > self.size:
                raise _corrupt()
            spans.append((info.header_offset, end, info))
        spans.sort(key=lambda t: t[0])
        for (_s1, e1, _i1), (s2, _e2, _i2) in itertools.pairwise(spans):
            if e1 > s2:
                raise unsupported_workbook(
                    "zip.overlapping_entries", "The package contains overlapping entries."
                )
        for _s, _e, info in spans:
            self._check_local_name(info)

    def _local_header(self, info: zipfile.ZipInfo) -> tuple[int, int]:
        self._f.seek(info.header_offset)
        raw = self._f.read(30)
        if len(raw) < 30 or raw[:4] != _LOCAL:
            raise _corrupt()
        name_len, extra_len = struct.unpack_from("<HH", raw, 26)
        return int(name_len), int(extra_len)

    def _data_start(self, info: zipfile.ZipInfo) -> int:
        name_len, extra_len = self._local_header(info)
        return info.header_offset + 30 + name_len + extra_len

    def _check_local_name(self, info: zipfile.ZipInfo) -> None:
        name_len, _extra = self._local_header(info)
        self._f.seek(info.header_offset + 30)
        raw = self._f.read(name_len)
        want = info.filename.encode("utf-8" if info.flag_bits & 0x800 else "cp437", "replace")
        if raw != want:
            raise import_failed(
                "zip.local_header_mismatch", "The package headers are inconsistent."
            )

    # -- reads -------------------------------------------------------------------------------
    def names(self) -> list[str]:
        return [i.filename for i in self.infos]

    def iter_chunks(self, name: str) -> Iterator[bytes]:
        """Decompressed bytes of one entry, counted against the budgets as they are produced."""
        info = self.by_name[name]
        produced = 0
        try:
            with self._zf.open(info) as fh:
                while True:
                    chunk = fh.read(_READ)
                    if not chunk:
                        break
                    produced += len(chunk)
                    self.total_read += len(chunk)
                    if produced > info.file_size:
                        raise import_failed(
                            "zip.size_mismatch", "A package entry is larger than it declares."
                        )
                    if self.total_read > self.limits.max_uncompressed_bytes:
                        raise unsupported_workbook(
                            "zip.uncompressed_too_large",
                            "The package expands to more than the allowed size.",
                        )
                    yield chunk
                    self.deadline.check()
        except zipfile.BadZipFile:
            raise import_failed("zip.bad_crc", "A package entry failed its integrity check.") from None
        except (zlib.error, EOFError, NotImplementedError, OSError):
            raise import_failed("zip.corrupt", "A package entry is damaged.") from None
        if produced != info.file_size:
            raise import_failed("zip.size_mismatch", "A package entry is shorter than it declares.")

    def read(self, name: str) -> bytes:
        return b"".join(self.iter_chunks(name))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._zf.close()
        self._f.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a: object) -> None:
        self.close()
