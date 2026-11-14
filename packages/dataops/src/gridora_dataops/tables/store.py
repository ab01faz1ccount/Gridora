"""ParquetTableStore: immutable Parquet versions (ADR-005).

Layout contract with apps/api: `path_for(owner_id, table_id, version)` returns the file for one version; **all
versions of one table must live in the same directory** (the store keeps a small `table.json` index next to them).
The index records which versions exist and their schema; it is NOT the 'current version' pointer, which
Postgres/API owns (the API passes the version it wants, or the store uses the highest one and says so).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
from gridora_contracts.models import Cell, Column, DataTable, Delta, Range, Warning_
from gridora_contracts.protocols import ExecContext

from ..conversions import POLARS_DTYPES, convert_column
from ..errors import DataOpsError, pointer
from ..persian.chars import collation_key
from ..targets import to_cell_rows
from .bridge import TableImportPreview, a1, import_range, preview_of
from .frames import columns_of, normalize_frame, rows_of

PathResolver = Callable[[str, str, int], Path]
ROW_GROUP_SIZE = 65_536


class ParquetTableStore:
    def __init__(self, path_for: PathResolver, owner_id: str | None = None, *,
                 max_patch_cells: int = 200_000,
                 new_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._path_for = path_for
        self._owner_id = owner_id
        self._max_cells = max_patch_cells
        self._new_id = new_id

    def for_owner(self, owner_id: str) -> ParquetTableStore:
        """A store bound to one owner. Needed for the contract methods that carry no ExecContext
        (`read_page`, `restore_version`); see CONTRACT_CHANGE note in the PR."""
        return ParquetTableStore(self._path_for, owner_id, max_patch_cells=self._max_cells, new_id=self._new_id)

    # ------------------------------------------------------------------ paths / index
    def _owner(self, ctx: ExecContext | None = None) -> str:
        owner = ctx.user_id if ctx is not None else self._owner_id
        if not owner:
            raise DataOpsError("owner_unknown", "this store is not bound to an owner; call for_owner(user_id)")
        return owner

    def _file(self, owner: str, table_id: str, version: int) -> Path:
        return self._path_for(owner, table_id, version)

    def _index_path(self, owner: str, table_id: str) -> Path:
        return self._file(owner, table_id, 1).parent / "table.json"

    def _read_index(self, owner: str, table_id: str) -> dict[str, Any]:
        p = self._index_path(owner, table_id)
        if not p.exists():
            raise DataOpsError("table_not_found", f"table '{table_id}' does not exist", path=pointer("target", "table_id"))
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return data

    def _write_index(self, owner: str, table_id: str, index: dict[str, Any]) -> None:
        p = self._index_path(owner, table_id)
        tmp = p.with_name(f"table.json.tmp-{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(index, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    def versions(self, owner: str, table_id: str) -> list[int]:
        idx = self._read_index(owner, table_id)
        return sorted(int(v) for v, m in idx["versions"].items()
                      if not m.get("compacted") and self._file(owner, table_id, int(v)).exists())

    def latest_version(self, owner: str, table_id: str) -> int:
        vs = self.versions(owner, table_id)
        if not vs:
            raise DataOpsError("version_unavailable", "table has no available version")
        return vs[-1]

    # ------------------------------------------------------------------ writing
    def _write_parquet(self, path: Path, frame: pl.DataFrame) -> str:
        """Atomic, never overwrites: temp file + fsync + hard link (fails if the version exists)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
        try:
            frame.write_parquet(tmp, compression="zstd", row_group_size=ROW_GROUP_SIZE)
            with tmp.open("rb") as f:
                os.fsync(f.fileno())
                digest = hashlib.sha256()
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise DataOpsError("version_conflict", "this table version already exists (versions are immutable)") from None
        finally:
            tmp.unlink(missing_ok=True)
        return digest.hexdigest()

    def _table(self, workspace_id: str, name: str, table_id: str, version: int, frame: pl.DataFrame) -> DataTable:
        return DataTable(id=table_id, workspace_id=workspace_id, name=name, version=version,
                         columns=columns_of(frame), row_count=frame.height)

    def create_table(self, owner: str, workspace_id: str, name: str, frame: pl.DataFrame) -> DataTable:
        frame = normalize_frame(frame)
        table_id = self._new_id()
        sha = self._write_parquet(self._file(owner, table_id, 1), frame)
        dt = self._table(workspace_id, name, table_id, 1, frame)
        self._write_index(owner, table_id, {"table_id": table_id, "name": name, "workspace_id": workspace_id,
                                            "versions": {"1": {"sha256": sha, "parent": None, "row_count": frame.height,
                                                               "columns": [c.model_dump() for c in dt.columns]}}})
        return dt

    def write_version(self, owner: str, table_id: str, frame: pl.DataFrame, *, parent: int) -> DataTable:
        """New immutable version number = highest ever used + 1 (numbers are never reused)."""
        frame = normalize_frame(frame)
        idx = self._read_index(owner, table_id)
        new = max(int(v) for v in idx["versions"]) + 1
        sha = self._write_parquet(self._file(owner, table_id, new), frame)
        dt = self._table(idx["workspace_id"], idx["name"], table_id, new, frame)
        idx["versions"][str(new)] = {"sha256": sha, "parent": parent, "row_count": frame.height,
                                     "columns": [c.model_dump() for c in dt.columns]}
        self._write_index(owner, table_id, idx)
        return dt

    def discard_version(self, owner: str, table_id: str, version: int) -> None:
        """Rollback of a version written by a failed pipeline run: the file goes, the number stays retired."""
        idx = self._read_index(owner, table_id)
        if str(version) in idx["versions"]:
            idx["versions"][str(version)]["compacted"] = True
            self._write_index(owner, table_id, idx)
        self._file(owner, table_id, version).unlink(missing_ok=True)

    def discard_table(self, owner: str, table_id: str) -> None:
        """Rollback of a table created by a failed pipeline run (all its files and its index)."""
        idx = self._read_index(owner, table_id)
        for v in idx["versions"]:
            self._file(owner, table_id, int(v)).unlink(missing_ok=True)
        index_path = self._index_path(owner, table_id)
        index_path.unlink(missing_ok=True)
        try:
            index_path.parent.rmdir()
        except OSError:
            pass  # not empty (or already gone): leave it

    # ------------------------------------------------------------------ reading
    def read_frame(self, owner: str, table_id: str, version: int | None = None) -> tuple[pl.DataFrame, int]:
        idx = self._read_index(owner, table_id)
        v = version if version is not None else self.latest_version(owner, table_id)
        meta = idx["versions"].get(str(v))
        path = self._file(owner, table_id, v)
        if meta is None or meta.get("compacted") or not path.exists():
            raise DataOpsError("version_unavailable", f"version {v} of table '{table_id}' is not available")
        return pl.read_parquet(path), v

    # ------------------------------------------------------------------ TableStore protocol
    def create_from_rows(self, ctx: ExecContext, name: str, columns: list[Any], rows: list[list[Any]]) -> DataTable:
        cols = [c if isinstance(c, Column) else Column.model_validate(c) for c in columns]
        data: dict[str, pl.Series] = {}
        for j, c in enumerate(cols):
            values = [r[j] if j < len(r) else None for r in rows]
            try:
                if c.dtype in ("date", "datetime") and any(isinstance(v, str) for v in values):
                    s = pl.Series(c.name, values, dtype=pl.String)
                    data[c.name] = convert_column(pl.DataFrame({c.name: s}), c.name, c.dtype, on_error="fail"
                                                  ).frame[c.name]
                else:
                    data[c.name] = pl.Series(c.name, values, dtype=POLARS_DTYPES[c.dtype])
            except (TypeError, pl.exceptions.PolarsError) as e:
                raise DataOpsError("type_mismatch", f"column '{c.name}' does not fit {c.dtype}: {e}",
                                   path=pointer("columns", j)) from None
        return self.create_table(self._owner(ctx), ctx.workspace_id, name, pl.DataFrame(data))

    def read_page(self, table_id: str, offset: int, limit: int, sort: str | None = None,
                  version: int | None = None) -> list[list[Any]]:
        """`sort`: a column name, `-name` for descending. Text sorts with the Persian-aware collation; stable."""
        owner = self._owner()
        idx = self._read_index(owner, table_id)
        v = version if version is not None else self.latest_version(owner, table_id)
        path = self._file(owner, table_id, v)
        if idx["versions"].get(str(v)) is None or not path.exists():
            raise DataOpsError("version_unavailable", f"version {v} of table '{table_id}' is not available")
        lf = pl.scan_parquet(path)
        if sort:
            desc = sort.startswith("-")
            col = sort[1:] if sort[:1] in "+-" else sort
            names = lf.collect_schema()
            if col not in names:
                raise DataOpsError("unknown_column", f"cannot sort by unknown column '{col}'", path=pointer("sort"))
            key = collation_key(pl.col(col)) if names[col] == pl.String else pl.col(col)
            lf = lf.with_columns(key.alias("__k")).sort("__k", descending=desc, nulls_last=True,
                                                         maintain_order=True).drop("__k")
        return rows_of(lf.slice(max(offset, 0), max(limit, 0)).collect())

    def sheet_range_to_table(self, ctx: ExecContext, rng: Range, header_row: bool,
                             dtype_overrides: dict[str, str] | None = None,
                             preview: bool = False) -> DataTable | TableImportPreview:
        """`preview=True` returns a TableImportPreview (schema, first rows, warnings) and stores nothing."""
        frame, warnings = import_range(ctx, rng, header_row, dtype_overrides)
        if preview:
            return preview_of(frame, warnings)
        return self.create_table(self._owner(ctx), ctx.workspace_id, f"Table {a1(rng)}", frame)

    def table_to_cells(self, table_id: str, ctx: ExecContext, anchor: Range, version: int | None = None) -> Delta:
        """Write header + rows starting at the anchor's top-left cell. Never overwrites non-empty cells and
        never exceeds the per-patch cell cap (`too_large_for_history`)."""
        frame, _v = self.read_frame(self._owner(ctx), table_id, version)
        rows = to_cell_rows(frame, list(frame.columns))
        height, width = len(rows), max(frame.width, 1)
        if height * width > self._max_cells:
            raise DataOpsError("too_large_for_history", f"{height * width} cells exceed the limit of {self._max_cells}")
        full = Range(sheet_id=anchor.sheet_id, r0=anchor.r0, c0=anchor.c0, r1=anchor.r0 + height - 1,
                     c1=anchor.c0 + width - 1)
        for row in ctx.read_range(full):
            if any(isinstance(c, Cell) and (c.v is not None or c.f is not None) for c in row):
                raise DataOpsError("would_overwrite", "the target area already contains data", path=pointer("anchor"))
        return ctx.write_range(full, rows)

    def restore_version(self, table_id: str, version: int) -> DataTable:
        """Pointer swap: returns the existing DataTable at `version`; writes nothing."""
        owner = self._owner()
        idx = self._read_index(owner, table_id)
        meta = idx["versions"].get(str(version))
        if meta is None or meta.get("compacted") or not self._file(owner, table_id, version).exists():
            raise DataOpsError("version_unavailable", f"version {version} of table '{table_id}' is not available")
        return DataTable(id=table_id, workspace_id=idx["workspace_id"], name=idx["name"], version=version,
                         columns=[Column.model_validate(c) for c in meta["columns"]], row_count=meta["row_count"])


__all__ = ["ParquetTableStore", "PathResolver", "TableImportPreview", "Warning_"]
