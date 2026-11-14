"""argon2id password hashing. CPU-heavy: always call the async wrappers (worker thread)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from starlette.concurrency import run_in_threadpool

from ..config import Settings


class Hasher:
    def __init__(self, settings: Settings) -> None:
        self._ph = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
        )  # argon2-cffi's PasswordHasher produces argon2id
        # Verified against when the username does not exist, so timing does not reveal it.
        self._dummy = self._ph.hash("gridora-dummy-password")

    def _verify(self, hash_: str, password: str) -> bool:
        try:
            return self._ph.verify(hash_, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    async def hash(self, password: str) -> str:
        return await run_in_threadpool(self._ph.hash, password)

    async def verify(self, hash_: str | None, password: str) -> bool:
        if hash_ is None:
            await run_in_threadpool(self._verify, self._dummy, password)
            return False
        return await run_in_threadpool(self._verify, hash_, password)

    def needs_rehash(self, hash_: str) -> bool:
        return self._ph.check_needs_rehash(hash_)
