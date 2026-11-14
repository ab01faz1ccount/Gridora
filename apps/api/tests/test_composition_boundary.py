"""MODULE_BOUNDARIES: only composition/wiring.py may mention the real modules."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "gridora_api"
REAL = ("gridora_engine", "gridora_dataops")
ALLOWED = {SRC / "composition" / "wiring.py"}


def _py() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imported(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out


def test_real_modules_are_never_imported_statically() -> None:
    # wiring.py loads them lazily via importlib, so NO file imports them with an import statement.
    bad = [str(p) for p in _py() if _imported(ast.parse(p.read_text())) & set(REAL)]
    assert bad == []


def test_real_module_names_are_not_used_as_strings_outside_wiring() -> None:
    """importlib.import_module("gridora_engine") elsewhere would bypass the boundary."""
    bad = []
    for p in _py():
        if p in ALLOWED:
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in REAL:
                bad.append(str(p))
    assert bad == []


def test_wiring_only_uses_the_four_fixed_factories() -> None:
    text = (SRC / "composition" / "wiring.py").read_text()
    for name in ("create_engine", "create_executor", "create_table_store", "catalog"):
        assert f'"{name}"' in text
    assert text.count("_load(") == 3  # one load per real module use, nothing else


def test_contracts_are_not_redefined_locally() -> None:
    # The api consumes gridora_contracts models; it must not ship its own Cell/Delta/Workbook.
    for p in _py():
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.ClassDef):
                assert n.name not in {"Cell", "Delta", "Workbook", "FileRecord", "Operation"}, p
