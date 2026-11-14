"""In-memory working copies of open workbooks (single process in v1).

A WorkbookHandle is owned by the engine and is not thread-safe, so every engine call on a document
runs under that document's threading lock (inside a worker thread, never on the event loop).
Locks are threading locks on purpose: they do not belong to any asyncio loop.

Eviction (LRU, capped by settings.max_open_workbooks) closes the handle; state is reconstructible
from the stored file (and, from PR 10 on, the replayed history), so eviction is safe.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from gridora_contracts.models import Workbook
from gridora_contracts.protocols import WorkbookEngine, WorkbookHandle
from starlette.concurrency import run_in_threadpool

T = TypeVar("T")


@dataclass
class Entry:
    handle: WorkbookHandle
    workbook: Workbook
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_used: float = field(default_factory=time.monotonic)


class WorkingCopies:
    def __init__(self, engine: WorkbookEngine, max_open: int) -> None:
        self.engine, self.max_open = engine, max_open
        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._guard = threading.Lock()  # protects _entries and _loading
        self._loading: dict[str, threading.Lock] = {}

    def __len__(self) -> int:
        with self._guard:
            return len(self._entries)

    def is_open(self, doc_id: str) -> bool:
        with self._guard:
            return doc_id in self._entries

    def put(self, doc_id: str, handle: WorkbookHandle, workbook: Workbook) -> Entry:
        entry = Entry(handle, workbook)
        with self._guard:
            old = self._entries.pop(doc_id, None)
            self._entries[doc_id] = entry
            victims = self._pick_victims()
        if old is not None:
            self._close(old)
        for v in victims:
            self._close(v)
        return entry

    def _pick_victims(self) -> list[Entry]:  # caller holds _guard
        out: list[Entry] = []
        for key in list(self._entries):
            if len(self._entries) <= self.max_open:
                break
            e = self._entries[key]
            if e.lock.locked():  # in use right now: skip, may exceed the cap temporarily
                continue
            out.append(self._entries.pop(key))
        return out

    def _close(self, e: Entry) -> None:
        with e.lock:
            self.engine.close(e.handle)

    def drop(self, doc_id: str) -> None:
        with self._guard:
            e = self._entries.pop(doc_id, None)
        if e is not None:
            self._close(e)

    def get(self, doc_id: str) -> Entry | None:
        with self._guard:
            e = self._entries.get(doc_id)
            if e is not None:
                self._entries.move_to_end(doc_id)
                e.last_used = time.monotonic()
            return e

    def load_blocking(
        self, doc_id: str, loader: Callable[[], tuple[WorkbookHandle, Workbook]]
    ) -> Entry:
        """Return the open entry, loading it at most once even under concurrent callers.
        Runs in a worker thread (the loader parses a file)."""
        with self._guard:
            gate = self._loading.setdefault(doc_id, threading.Lock())
        with gate:
            existing = self.get(doc_id)
            if existing is not None:
                return existing
            handle, wb = loader()
            return self.put(doc_id, handle, wb)

    async def load(
        self, doc_id: str, loader: Callable[[], tuple[WorkbookHandle, Workbook]]
    ) -> Entry:
        return await run_in_threadpool(self.load_blocking, doc_id, loader)

    async def call(self, entry: Entry, fn: Callable[..., T], *args: Any, **kw: Any) -> T:
        """Run an engine call on this document, serialized, off the event loop."""

        def locked() -> T:
            with entry.lock:
                return fn(*args, **kw)

        return await run_in_threadpool(locked)

    def close_all(self) -> None:
        with self._guard:
            entries = list(self._entries.values())
            self._entries.clear()
        for e in entries:
            self._close(e)
