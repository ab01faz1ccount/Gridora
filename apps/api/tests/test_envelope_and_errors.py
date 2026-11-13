from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from gridora_contracts.models import ERROR_CODES, ErrorDetail
from pydantic import BaseModel, Field

from gridora_api.config import Settings
from gridora_api.core.envelope import Envelope, ok
from gridora_api.core.errors import STATUS_BY_CODE, DomainError
from gridora_api.main import create_app


class Item(BaseModel):
    n: int = Field(ge=0)


class Body(BaseModel):
    items: list[Item]


@pytest.fixture
def tapp(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/t/ok", response_model=Envelope[Item])
    async def t_ok(request: Request) -> Envelope[Item]:
        return ok(request, Item(n=1), next_cursor="abc")

    @app.get("/t/domain")
    async def t_domain() -> None:
        raise DomainError(
            "version_conflict",
            details=[ErrorDetail(code="seq.stale", path="/base_seq", message="stale")],
        )

    @app.post("/t/body")
    async def t_body(body: Body) -> dict[str, int]:
        return {"n": len(body.items)}

    @app.get("/t/boom")
    async def t_boom() -> None:
        raise RuntimeError("secret /var/lib/gridora/users/abc password=hunter2")

    return app


@pytest.fixture
def tclient(tapp: FastAPI) -> Iterator[TestClient]:
    with TestClient(tapp, raise_server_exceptions=False) as c:
        yield c


def test_status_table_matches_contract_error_codes() -> None:
    assert set(STATUS_BY_CODE) == set(ERROR_CODES)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("bad_request", 400),
        ("validation_failed", 400),
        ("unauthenticated", 401),
        ("forbidden", 403),
        ("not_found", 404),
        ("version_conflict", 409),
        ("operation_conflict", 409),
        ("file_too_large", 413),
        ("unsupported_media_type", 415),
        ("unsupported_workbook", 422),
        ("import_failed", 422),
        ("rate_limited", 429),
        ("internal_error", 500),
    ],
)
def test_statuses_follow_api_contracts_table(code: str, status: int) -> None:
    assert STATUS_BY_CODE[code] == status


def test_unknown_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        DomainError("made_up")


def test_success_envelope(tclient: TestClient) -> None:
    r = tclient.get("/t/ok")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == {"n": 1}
    assert body["meta"]["next_cursor"] == "abc"
    assert body["meta"]["request_id"] == r.headers["X-Request-ID"]


def test_domain_error_envelope(tclient: TestClient) -> None:
    r = tclient.get("/t/domain")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "version_conflict"
    assert err["details"] == [{"code": "seq.stale", "path": "/base_seq", "message": "stale"}]
    assert err["request_id"] == r.headers["X-Request-ID"]


def test_validation_error_is_400_with_json_pointer(tclient: TestClient) -> None:
    r = tclient.post("/t/body", json={"items": [{"n": 1}, {"n": -5}]})
    assert r.status_code == 400  # not FastAPI's default 422
    err = r.json()["error"]
    assert err["code"] == "validation_failed"
    assert [d["path"] for d in err["details"]] == ["/items/1/n"]
    assert err["details"][0]["code"].startswith("validation.")
    assert "-5" not in r.text  # the submitted value is not echoed back


def test_unknown_route_is_404_not_found(tclient: TestClient) -> None:
    r = tclient.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_wrong_method_is_405_with_envelope(tclient: TestClient) -> None:
    r = tclient.post("/t/ok")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "bad_request"


def test_unhandled_exception_leaks_nothing(tclient: TestClient) -> None:
    r = tclient.get("/t/boom")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "internal_error"
    for leak in ("secret", "/var/lib", "hunter2", "Traceback", "RuntimeError", "gridora_api"):
        assert leak not in r.text
    assert err["request_id"] == r.headers["X-Request-ID"] != "unknown"


def test_request_id_is_propagated_when_safe(tclient: TestClient) -> None:
    r = tclient.get("/t/ok", headers={"X-Request-ID": "abc-12345678"})
    assert r.headers["X-Request-ID"] == "abc-12345678"
    assert r.json()["meta"]["request_id"] == "abc-12345678"


def test_unsafe_request_id_is_replaced(tclient: TestClient) -> None:
    r = tclient.get("/t/ok", headers={"X-Request-ID": "bad id\twith spaces!"})
    rid = r.headers["X-Request-ID"]
    assert rid != "bad id\twith spaces!"
    assert len(rid) == 32


def test_security_headers_on_success_and_error(tclient: TestClient) -> None:
    for path in ("/t/ok", "/t/domain", "/t/boom", "/nope"):
        r = tclient.get(path)
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
