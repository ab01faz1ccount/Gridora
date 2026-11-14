"""The ONLY place that builds filesystem paths. Clients never see them (SECURITY_MODEL).

Layout:  ${DATA_ROOT}/quarantine/<uuid>                     uploads while being validated
         ${DATA_ROOT}/users/<owner_uuid>/<kind>/<file_uuid>[.<ext>]
         ${DATA_ROOT}/users/<owner_uuid>/tables/<table_uuid>/v<version>.parquet
Every component is a UUID or comes from a fixed allowlist, never from user input.
"""

from __future__ import annotations

import uuid
from pathlib import Path

KINDS = ("original", "workbook", "table", "export")
EXTENSIONS = ("xlsx", "xlsm", "csv", "parquet")


def _u(value: str | uuid.UUID) -> str:
    return str(uuid.UUID(str(value)))  # raises ValueError for anything that is not a UUID


class StorageLayout:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _inside(self, p: Path) -> Path:
        if not p.resolve().is_relative_to(self.root):
            raise ValueError("path escapes the data root")
        return p

    def quarantine_path(self, upload_id: str | uuid.UUID) -> Path:
        return self._inside(self.root / "quarantine" / _u(upload_id))

    def file_key(
        self, owner_id: str | uuid.UUID, kind: str, file_id: str | uuid.UUID, ext: str | None
    ) -> str:
        """Relative storage key (this is what the database stores)."""
        if kind not in KINDS:
            raise ValueError("unknown kind")
        if ext is not None and ext not in EXTENSIONS:
            raise ValueError("extension not allowed")
        name = _u(file_id) + (f".{ext}" if ext else "")
        return f"users/{_u(owner_id)}/{kind}/{name}"

    def resolve_key(self, key: str) -> Path:
        return self._inside(self.root / key)

    def table_path(self, owner_id: str, table_id: str, version: int) -> Path:
        """Implements contracts PathResolver(owner_id, table_id, version)."""
        if version < 1:
            raise ValueError("version must be >= 1")
        return self._inside(
            self.root
            / "users"
            / _u(owner_id)
            / "tables"
            / _u(table_id)
            / f"v{int(version)}.parquet"
        )

    def ensure_dirs(self) -> None:
        for d in (self.root, self.root / "quarantine", self.root / "users"):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
