from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gridora_api.composition.stubs import catalog_stub, engine_stub, executor_stub
from gridora_api.composition.wiring import CompositionError, build_services
from gridora_api.main import create_app
from gridora_api.storage.layout import StorageLayout

from .conftest import fast_settings


def layout(tmp_path: Path) -> StorageLayout:
    return StorageLayout(tmp_path / "data")


def test_default_is_stub_and_loads_all_protocols(tmp_path: Path) -> None:
    s = build_services(fast_settings(tmp_path), layout(tmp_path))
    assert (s.engine_kind, s.dataops_kind) == ("stub", "stub")
    assert not s.formatting_available and not s.structure_available  # feature detection: absent
    assert s.catalog("fa")["ops.sort.label"] == "مرتب‌سازی"


@pytest.mark.parametrize("which", ["engine", "dataops"])
def test_real_without_the_package_fails_at_startup_with_a_clear_message(
    tmp_path: Path, which: str
) -> None:
    with pytest.raises(CompositionError, match="not installed"):
        build_services(fast_settings(tmp_path, **{which: "real"}), layout(tmp_path))
    with pytest.raises(CompositionError):
        create_app(fast_settings(tmp_path, **{which: "real"}))


@pytest.fixture
def fake_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand-in 'real' packages exposing exactly the fixed factories (contracts protocols.py)."""
    eng = types.ModuleType("gridora_engine")
    eng.create_engine = lambda config: engine_stub.create_engine(config)  # type: ignore[attr-defined]
    ops = types.ModuleType("gridora_dataops")
    ops.create_executor = executor_stub.create_executor  # type: ignore[attr-defined]
    ops.create_table_store = executor_stub.create_table_store  # type: ignore[attr-defined]
    ops.catalog = catalog_stub.catalog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gridora_engine", eng)
    monkeypatch.setitem(sys.modules, "gridora_dataops", ops)


def test_swapping_to_real_is_one_setting_per_module(tmp_path: Path, fake_real: None) -> None:
    s = build_services(fast_settings(tmp_path, engine="real", dataops="real"), layout(tmp_path))
    assert (s.engine_kind, s.dataops_kind) == ("real", "real")
    app = create_app(fast_settings(tmp_path, engine="real", dataops="real"))
    with TestClient(app) as c:
        r = c.get("/readyz")
        assert r.json()["implementations"] == {"engine": "real", "dataops": "real"}
        assert r.headers["x-gridora-engine"] == "real"


def test_table_store_receives_the_api_path_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    ops = types.ModuleType("gridora_dataops")
    ops.create_executor = executor_stub.create_executor  # type: ignore[attr-defined]

    def mk(path_for: Any) -> Any:
        seen["p"] = path_for
        return executor_stub.create_table_store(path_for)

    ops.create_table_store = mk  # type: ignore[attr-defined]
    ops.catalog = catalog_stub.catalog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gridora_dataops", ops)
    lay = layout(tmp_path)
    build_services(fast_settings(tmp_path, dataops="real"), lay)
    u = "123e4567-e89b-12d3-a456-426614174000"
    assert seen["p"](u, u, 2) == lay.table_path(
        u, u, 2
    )  # PathResolver(owner_id, table_id, version)


def test_missing_factory_or_wrong_type_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "gridora_engine", types.ModuleType("gridora_engine"))
    with pytest.raises(CompositionError, match="create_engine"):
        build_services(fast_settings(tmp_path, engine="real"), layout(tmp_path))
    bad = types.ModuleType("gridora_engine")
    bad.create_engine = lambda config: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gridora_engine", bad)
    with pytest.raises(CompositionError, match="WorkbookEngine"):
        build_services(fast_settings(tmp_path, engine="real"), layout(tmp_path))


def test_stub_is_visible_on_every_response(client: TestClient) -> None:
    for path in ("/healthz", "/readyz", "/api/v1/auth/me", "/api/v1/nope"):
        r = client.get(path)
        assert r.headers["x-gridora-engine"] == "stub", path
        assert r.headers["x-gridora-dataops"] == "stub", path
    body = client.get("/readyz").json()
    assert body["implementations"] == {"engine": "stub", "dataops": "stub"}
    assert body["checks"]["composition"] == "ok"
