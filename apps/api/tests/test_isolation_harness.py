"""Isolation harness (PLAN 2.4). Fails if a route with an id parameter has no isolation case, and
executes every case as a second user. New routes cannot silently skip isolation."""

from __future__ import annotations

from fastapi import FastAPI

from .conftest import Session, run_db
from .helpers import import_csv
from .isolation_cases import ISOLATION_CASES
from .routes import implemented_routes


def uncovered_routes(app: FastAPI, cases: dict[tuple[str, str], object]) -> list[tuple[str, str]]:
    return sorted((m, p) for m, p in implemented_routes(app) if "{" in p and (m, p) not in cases)


def test_all_id_routes_have_an_isolation_case(app: FastAPI) -> None:
    assert uncovered_routes(app, ISOLATION_CASES) == []


def test_harness_detects_an_uncovered_route(app: FastAPI) -> None:
    @app.get("/api/v1/widgets/{widget_id}")
    async def widget(widget_id: str) -> None: ...

    assert uncovered_routes(app, ISOLATION_CASES) == [("GET", "/api/v1/widgets/{widget_id}")]


def test_every_case_is_404_for_another_user_and_changes_nothing(
    alice: Session, bob: Session
) -> None:
    ws = alice.post("/api/v1/workspaces", json={"name": "alice-ws"}).json()["data"]["id"]
    ids = {"ws": ws, **import_csv(alice, ws, "x.csv", b"a,b\n1,2\n")}
    ids["table"] = _a_table_of(alice, ws)
    for key, case in ISOLATION_CASES.items():
        r = case(bob, ids)
        assert r.status_code == 404, f"{key}: another user got {r.status_code}"
        assert r.json()["error"]["code"] == "not_found"
        assert case(_anon(bob), ids).status_code == 401, key
    # nothing was changed or deleted by bob
    got = alice.get(f"/api/v1/workspaces/{ws}").json()["data"]
    assert got["name"] == "alice-ws"
    assert len(alice.get(f"/api/v1/workspaces/{ws}/files").json()["data"]) == 1
    assert alice.get(f"/api/v1/workbooks/{ids['wb']}").status_code == 200
    assert alice.get(f"/api/v1/files/{ids['file']}/download").status_code == 200


def _anon(s: Session):  # type: ignore[no-untyped-def]
    """A client with no cookies and no CSRF token."""
    from .conftest import ScanningClient

    c = ScanningClient(s.client.app, base_url="https://testserver", raise_server_exceptions=False)
    c.forbidden = s.client.forbidden
    return c


def _a_table_of(owner: Session, workspace_id: str) -> str:
    """A table row owned by `owner` (metadata only: the isolation checks never read its data)."""
    import uuid

    from gridora_api.db.models import DataTableRow, Document

    me = uuid.UUID(owner.get("/api/v1/auth/me").json()["data"]["user"]["id"])
    tid = uuid.uuid4()

    async def go(db):  # type: ignore[no-untyped-def]
        db.add(Document(id=tid, owner_id=me, kind="table"))
        await db.flush()
        db.add(
            DataTableRow(
                id=tid,
                owner_id=me,
                workspace_id=uuid.UUID(workspace_id),
                name="t",
                current_version=1,
                meta_json={},
            )
        )

    run_db(go)
    return str(tid)
