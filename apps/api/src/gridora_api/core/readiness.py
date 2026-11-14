"""Readiness registry. Later PRs register their own checks (database, engine adapter)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

Check = Callable[[], Awaitable[bool]]


class ReadinessRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, Check] = {}

    def register(self, name: str, check: Check) -> None:
        self._checks[name] = check

    async def run(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, check in self._checks.items():
            try:
                results[name] = bool(await check())
            except Exception:  # noqa: BLE001 - never leak the reason to the client
                results[name] = False
        return results


def storage_writable_check(root: Path) -> Check:
    async def check() -> bool:
        probe = root / ".ready-probe"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True

    return check
