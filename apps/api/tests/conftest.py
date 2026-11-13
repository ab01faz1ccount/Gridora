from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gridora_api.config import Settings
from gridora_api.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(env="test", data_root=tmp_path / "data", secure_cookies=True)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False: we want to see the 500 response a real client would get.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
