"""Atomic file placement: write to a temp name, fsync, rename, fsync the directory."""

from __future__ import annotations

import os
from pathlib import Path


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def move_into_place(src: Path, dst: Path) -> None:
    """Move a finished file to its final path. Never overwrites an existing file."""
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if dst.exists():
        raise FileExistsError("refusing to overwrite an existing stored file")
    fsync_file(src)
    os.replace(src, dst)  # atomic on the same filesystem (quarantine lives under DATA_ROOT)
    os.chmod(dst, 0o600)
    fsync_dir(dst.parent)


def atomic_write_bytes(dst: Path, data: bytes) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = dst.with_name(dst.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dst)
    fsync_dir(dst.parent)
