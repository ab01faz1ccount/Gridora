from __future__ import annotations

from pathlib import Path

import pytest
from gridora_contracts.models import FileRecord, Workspace

from .conftest import Session


def test_create_list_get_rename(alice: Session) -> None:
    r = alice.post("/api/v1/workspaces", json={"name": "  تحلیل فروش  "})
    assert r.status_code == 201
    w = Workspace.model_validate(r.json()["data"])  # contract model
    assert w.name == "تحلیل فروش" and w.owner_id == alice.user_id
    assert [x["id"] for x in alice.get("/api/v1/workspaces").json()["data"]] == [w.id]
    assert alice.get(f"/api/v1/workspaces/{w.id}").json()["data"]["name"] == "تحلیل فروش"
    r = alice.patch(f"/api/v1/workspaces/{w.id}", json={"name": "Sales 2026"})
    assert r.status_code == 200 and r.json()["data"]["name"] == "Sales 2026"


def test_lists_are_per_user(alice: Session, bob: Session) -> None:
    alice.post("/api/v1/workspaces", json={"name": "a"})
    assert bob.get("/api/v1/workspaces").json()["data"] == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {"name": "bad\x00name"},
        {"name": "ok", "owner_id": "x"},
    ],
)
def test_name_validation(alice: Session, body: dict[str, str]) -> None:
    r = alice.post("/api/v1/workspaces", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"


def test_malformed_and_unknown_ids_are_404(alice: Session) -> None:
    for wid in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        assert alice.get(f"/api/v1/workspaces/{wid}").status_code == 404


def test_mutations_need_csrf(alice: Session) -> None:
    del alice.client.headers["X-CSRF-Token"]
    r = alice.post("/api/v1/workspaces", json={"name": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_delete_requires_confirm_then_removes_rows_and_files(alice: Session, settings) -> None:  # type: ignore[no-untyped-def]
    ws = alice.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
    up = alice.post(f"/api/v1/workspaces/{ws}/files", files={"file": ("a.csv", b"a,b\n1,2\n")})
    fid = up.json()["data"]["file"]["id"]
    stored = list(Path(settings.data_root).rglob(f"{fid}*"))
    assert len(stored) == 1 and stored[0].is_file()

    r = alice.delete(f"/api/v1/workspaces/{ws}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "operation_conflict"
    assert alice.get(f"/api/v1/workspaces/{ws}").status_code == 200  # still there

    assert alice.delete(f"/api/v1/workspaces/{ws}?confirm=true").status_code == 204
    assert alice.get(f"/api/v1/workspaces/{ws}").status_code == 404
    assert alice.get(f"/api/v1/files/{fid}/download").status_code == 404
    assert not list(Path(settings.data_root).rglob(f"{fid}*"))  # bytes removed too


def test_file_list_shape_has_no_path(alice: Session) -> None:
    ws = alice.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
    alice.post(f"/api/v1/workspaces/{ws}/files", files={"file": ("a.csv", b"a\n1\n")})
    rows = alice.get(f"/api/v1/workspaces/{ws}/files").json()["data"]
    assert len(rows) == 1
    rec = FileRecord.model_validate(rows[0])
    assert rec.kind == "original" and rec.workspace_id == ws and rec.owner_id == alice.user_id
    assert set(rows[0]) == set(FileRecord.model_fields)  # exactly the contract fields
