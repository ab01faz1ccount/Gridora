"""Content-addressed blob store handed to the engine (contracts BlobStore, ADR-014).

Refs are the SHA-256 of the bytes (opaque to callers, never a path). Blobs are shared between users
by content, so a ref is only meaningful through a history entry the user already owns; no API route
returns a ref or a blob. Not used until the engine produces range snapshots (E5b). Garbage
collection of blobs that no history entry references is NOT implemented.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .atomic import atomic_write_bytes

_REF = re.compile(r"^[0-9a-f]{64}$")


class FileBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, ref: str) -> Path:
        if not _REF.match(ref):
            raise KeyError("unknown blob")  # never echo the ref back
        return self.root / ref[:2] / ref

    def put(self, data: bytes) -> str:
        ref = hashlib.sha256(data).hexdigest()
        p = self._path(ref)
        if not p.exists():
            atomic_write_bytes(p, data)
            os.chmod(p, 0o600)
        return ref

    def get(self, ref: str) -> bytes:
        p = self._path(ref)
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            raise KeyError("unknown blob") from None
        if hashlib.sha256(data).hexdigest() != ref:  # detect on-disk corruption
            raise KeyError("unknown blob")
        return data
