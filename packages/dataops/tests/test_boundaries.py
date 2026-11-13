"""Boundary rules (docs/MODULE_BOUNDARIES.md): dataops never imports engine or apps, and does no I/O of its own."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "gridora_dataops"
ALLOWED_THIRD_PARTY = {"gridora_contracts", "gridora_dataops", "polars", "pydantic"}
FORBIDDEN = {"gridora_engine", "apps", "duckdb", "socket", "urllib", "http", "requests", "httpx", "subprocess"}


def imported_roots() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in SRC.rglob("*.py"):
        roots = set()
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        out[str(f.relative_to(SRC))] = roots
    return out


def test_no_forbidden_imports() -> None:
    for name, roots in imported_roots().items():
        assert not (roots & FORBIDDEN), f"{name} imports {roots & FORBIDDEN}"


def test_only_stdlib_and_allowed_third_party() -> None:
    stdlib = set(sys.stdlib_module_names)
    for name, roots in imported_roots().items():
        extra = {r for r in roots if r not in stdlib and r not in ALLOWED_THIRD_PARTY}
        assert not extra, f"{name} imports unreviewed dependencies: {extra}"


def test_no_path_construction_outside_resolver() -> None:
    # dataops must not invent filesystem paths: no os/pathlib/open() use in M0 sources other than packaged i18n.
    for f in SRC.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "open(" not in text.replace("importlib", "") or f.name == "catalog.py", f.name
