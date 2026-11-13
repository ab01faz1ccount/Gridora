from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gridora_contracts.models import MAX_UPLOAD_BYTES, MAX_WINDOW_COLS, MAX_WINDOW_ROWS
from pydantic import ValidationError

from gridora_api.config import Settings
from gridora_api.main import create_app


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_ok_and_creates_data_root(client: TestClient, settings: Settings) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "checks": {"storage": "ok", "db": "ok", "composition": "ok"},
        "implementations": {"engine": "stub", "dataops": "stub"},
    }
    assert settings.data_root.is_dir()


def test_readyz_reports_failure_without_reason(tmp_path: Path) -> None:
    from .conftest import fast_settings

    app = create_app(fast_settings(tmp_path))

    async def broken() -> bool:
        raise OSError("disk /secret/path exploded")

    app.state.readiness.register("redis", broken)
    with TestClient(app) as c:
        r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["redis"] == "fail"
    assert "secret" not in r.text and "exploded" not in r.text


def test_infra_endpoints_are_not_in_openapi(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/healthz" not in paths and "/readyz" not in paths


def test_defaults_use_contract_limits() -> None:
    s = Settings()
    assert s.max_upload_bytes == MAX_UPLOAD_BYTES
    assert (s.max_window_rows, s.max_window_cols) == (MAX_WINDOW_ROWS, MAX_WINDOW_COLS)
    assert s.secure_cookies is True and s.engine == "stub" and s.dataops == "stub"


@pytest.mark.parametrize(
    "kw",
    [
        {"max_upload_bytes": MAX_UPLOAD_BYTES + 1},
        {"max_window_rows": MAX_WINDOW_ROWS + 1},
        {"max_window_cols": MAX_WINDOW_COLS + 1},
    ],
)
def test_limits_can_be_lowered_but_not_raised(kw: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(**kw)


def test_prod_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError):
        Settings(env="prod", secure_cookies=False)
    Settings(env="dev", secure_cookies=False)  # explicit dev opt-out is allowed
