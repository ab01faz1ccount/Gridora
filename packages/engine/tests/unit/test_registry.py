"""Honesty gate: supported/partial registry entries must point at tests that exist."""
import pathlib
import re

from gridora_engine.compat.registry import REGISTRY

TESTS = pathlib.Path(__file__).parent


def _all_test_names() -> set[str]:
    names: set[str] = set()
    for p in TESTS.rglob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)", p.read_text(encoding="utf-8"), re.MULTILINE))
    return names


def test_claimed_tiers_have_fixtures_and_existing_tests():
    names = _all_test_names()
    for code, f in REGISTRY.items():
        if f.tier in ("supported", "partial"):
            assert f.fixtures, code
            assert f.tests, code
            missing = [t for t in f.tests if t not in names]
            assert not missing, (code, missing)


def test_codes_are_unique_and_namespaced():
    assert all("." in c for c in REGISTRY)
