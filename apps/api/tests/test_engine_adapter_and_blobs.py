from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest
from gridora_contracts.protocols import BlobStore, ColumnarEngine, WorkbookEngine

from gridora_api.composition.engine_adapter import EngineErrorAdapter, translate
from gridora_api.composition.stubs.engine_stub import StubEngine
from gridora_api.core.errors import STATUS_BY_CODE, DomainError
from gridora_api.storage.blobs import FileBlobStore


class EngineError(Exception):
    """Same shape as the real engine's typed error (code, reason, public_message)."""

    def __init__(self, code: str, reason: str, public_message: str) -> None:
        super().__init__("INTERNAL DETAIL /srv/secret/path")
        self.code, self.reason, self.public_message = code, reason, public_message


class NotImpl(NotImplementedError):
    def __init__(self, method: str) -> None:
        super().__init__(method)
        self.method = method


# ----------------------------------------------------------------- translation ----
def test_engine_errors_become_domain_errors_with_the_engines_reason_as_detail() -> None:
    e = translate(EngineError("validation_failed", "edit.out_of_range", "Cell outside the sheet."))
    assert isinstance(e, DomainError)
    assert (e.code, e.message, e.status_code) == (
        "validation_failed",
        "Cell outside the sheet.",
        400,
    )
    assert e.details[0].code == "edit.out_of_range"


def test_too_large_for_history_is_always_operation_conflict() -> None:
    # Review 4 decision 2, whichever top-level code the engine used
    for code in ("validation_failed", "operation_conflict"):
        e = translate(EngineError(code, "too_large_for_history", "Too many cells."))
        assert e is not None and (e.code, e.status_code) == ("operation_conflict", 409)
        assert e.details[0].code == "too_large_for_history"


def test_unknown_codes_never_reach_the_client() -> None:
    e = translate(EngineError("made_up", "x.y", "private words"))
    assert e is not None and e.code == "internal_error" and "private" not in e.message


def test_not_implemented_is_a_typed_conflict_not_a_500() -> None:
    e = translate(NotImpl("export_xlsx"))
    assert e is not None and e.code == "operation_conflict"
    assert e.details[0].code == "engine.not_implemented"


def test_other_exceptions_are_not_translated() -> None:
    assert translate(RuntimeError("boom")) is None
    assert translate(ValueError("x")) is None


def test_every_translated_code_has_a_status() -> None:
    for code in STATUS_BY_CODE:
        e = translate(EngineError(code, "r", "m"))
        assert e is not None and e.code == code or code == "operation_conflict"


class Boom(StubEngine):
    def get_cells(self, *a: Any, **k: Any) -> Any:
        raise EngineError("not_found", "sheet.unknown", "The sheet does not exist.")

    def export_xlsx(self, *a: Any, **k: Any) -> Any:
        raise NotImpl("export_xlsx")

    def apply_cell_edits(self, *a: Any, **k: Any) -> Any:
        raise RuntimeError("crash with /private/path")


def test_adapter_translates_at_every_method_and_leaves_crashes_alone() -> None:
    a = EngineErrorAdapter(Boom())
    assert isinstance(a, WorkbookEngine)
    with pytest.raises(DomainError) as e1:
        a.get_cells(None, "s", None)
    assert e1.value.code == "not_found" and e1.value.details[0].code == "sheet.unknown"
    assert e1.value.__cause__ is None  # nothing from inside the engine is chained
    with pytest.raises(DomainError) as e2:
        a.export_xlsx(None, Path("x"))
    assert e2.value.code == "operation_conflict"
    with pytest.raises(RuntimeError):
        a.apply_cell_edits(None, "s", [])  # a real crash stays a crash (-> generic 500)


def test_optional_protocols_stay_detectable_through_the_adapter() -> None:
    assert not isinstance(EngineErrorAdapter(StubEngine()), ColumnarEngine)

    class WithColumnar(StubEngine):
        def read_range_columnar(self, *a: Any, **k: Any) -> Any:
            return None

        def write_range_columnar(self, *a: Any, **k: Any) -> Any:
            return None

    wrapped = EngineErrorAdapter(WithColumnar())
    assert isinstance(wrapped, ColumnarEngine)  # attached only because the engine has them


# ------------------------------------------------------------------ blob store ----
def test_blob_store_round_trip_and_protocol(tmp_path: Path) -> None:
    store = FileBlobStore(tmp_path / "blobs")
    assert callable(store.put) and callable(store.get)  # BlobStore is not runtime-checkable
    _: BlobStore = store  # (mypy checks the protocol statically)
    ref = store.put(b"hello")
    assert len(ref) == 64 and ref == store.put(b"hello")  # content-addressed, idempotent
    assert store.get(ref) == b"hello"
    assert str(tmp_path) not in ref  # a ref is not a path
    f = tmp_path / "blobs" / ref[:2] / ref
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


@pytest.mark.parametrize(
    "bad", ["", "../etc/passwd", "a" * 63, "g" * 64, "A" * 64, "x/../" + "a" * 60]
)
def test_blob_refs_are_validated_before_touching_the_disk(tmp_path: Path, bad: str) -> None:
    with pytest.raises(KeyError) as ei:
        FileBlobStore(tmp_path).get(bad)
    assert bad not in str(ei.value) or bad == ""  # the ref is not echoed back


def test_unknown_and_corrupted_blobs_are_refused(tmp_path: Path) -> None:
    store = FileBlobStore(tmp_path)
    with pytest.raises(KeyError):
        store.get("0" * 64)
    ref = store.put(b"data")
    (tmp_path / ref[:2] / ref).write_bytes(b"tampered")
    with pytest.raises(KeyError):
        store.get(ref)
