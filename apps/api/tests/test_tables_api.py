"""Data Tables end to end on the REAL engine and the REAL dataops package (Parquet on disk)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from gridora_contracts.models import DataTable, TablePreview, TableRows

from gridora_api.main import create_app

from .conftest import PASSWORD, ScanningClient, Session, fast_settings, forbidden_fragments
from .e2e_kit import Doc

pytest.importorskip("gridora_engine", reason="packages/engine is not installed")
pytest.importorskip("gridora_dataops", reason="packages/dataops is not installed")
pytest.importorskip("polars", reason="polars is not installed")

COLS = [{"name": "name", "dtype": "string"}, {"name": "qty", "dtype": "int64"}]
ROWS = [["علی", 3], ["رضا", 1], ["ب", 2]]


@pytest.fixture
def tuser(tmp_path: Path, make_user: Any) -> Iterator[Session]:
    app = create_app(fast_settings(tmp_path / "t", engine="real", dataops="real"))
    make_user("tara")
    c = ScanningClient(app, base_url="https://testserver", raise_server_exceptions=False)
    c.forbidden = forbidden_fragments(fast_settings(tmp_path / "t"))
    c.__enter__()
    r = c.post("/api/v1/auth/login", json={"username": "tara", "password": PASSWORD})
    yield Session(c, "tara", r.json()["data"]["csrf_token"])
    c.__exit__(None, None, None)


def _ws(s: Session) -> str:
    return str(s.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"])


def _make(s: Session, ws: str) -> DataTable:
    r = s.post(f"/api/v1/workspaces/{ws}/tables", json={"name": "T", "columns": COLS, "rows": ROWS})
    assert r.status_code == 201, r.text
    return DataTable.model_validate(r.json()["data"])


def test_create_get_list_and_page_rows(tuser: Session) -> None:
    ws = _ws(tuser)
    t = _make(tuser, ws)
    assert t.row_count == 3 and t.version == 1 and t.workspace_id == ws
    assert [c.name for c in t.columns] == ["name", "qty"]
    got = tuser.get(f"/api/v1/tables/{t.id}")
    assert got.status_code == 200 and DataTable.model_validate(got.json()["data"]).id == t.id
    listed = tuser.get(f"/api/v1/workspaces/{ws}/tables").json()["data"]
    assert [x["id"] for x in listed] == [t.id]

    page = TableRows.model_validate(tuser.get(f"/api/v1/tables/{t.id}/rows?limit=2").json()["data"])
    assert page.rows == [["علی", 3], ["رضا", 1]] and page.row_count == 3 and page.offset == 0
    desc = tuser.get(f"/api/v1/tables/{t.id}/rows?sort=-qty").json()["data"]["rows"]
    assert [r[1] for r in desc] == [3, 2, 1]
    assert tuser.get(f"/api/v1/tables/{t.id}/rows?sort=nope").status_code == 400


def test_bad_create_requests_are_typed_errors(tuser: Session) -> None:
    ws = _ws(tuser)
    bad = {"name": "T", "columns": COLS, "rows": [["x", "not a number"]]}
    r = tuser.post(f"/api/v1/workspaces/{ws}/tables", json=bad)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"
    assert tuser.get(f"/api/v1/workspaces/{ws}/tables").json()["data"] == []  # nothing registered
    for body in ({"name": "", "columns": COLS}, {"name": "T", "columns": []}):
        assert tuser.post(f"/api/v1/workspaces/{ws}/tables", json=body).status_code == 400
    assert tuser.get("/api/v1/tables/not-a-uuid").status_code == 404


def test_table_from_a_sheet_range_preview_then_create(tuser: Session) -> None:
    d = Doc(tuser, "real")
    rng = {"sheet_id": d.sheet, "r0": 0, "c0": 0, "r1": 2, "c1": 2}
    body: dict[str, Any] = {"workbook_id": d.wb, "range": rng, "header_row": True}
    pv = tuser.post("/api/v1/tables/from-range", json={**body, "preview": True})
    assert pv.status_code == 200, pv.text
    prev = TablePreview.model_validate(pv.json()["data"])
    assert [c.name for c in prev.columns] == ["نام", "تعداد", "شهر"] and prev.row_count == 2

    ws = tuser.get("/api/v1/workspaces").json()["data"][0]["id"]  # Doc made the only workspace
    stored = tuser.get(f"/api/v1/workspaces/{ws}/tables").json()["data"]
    assert stored == []  # the preview stored nothing
    r = tuser.post("/api/v1/tables/from-range", json={**body, "name": "From sheet"})
    assert r.status_code == 200, r.text
    t = DataTable.model_validate(r.json()["data"])
    assert t.name == "From sheet" and t.row_count == 2
    assert t.source is not None and t.source.workbook_id == d.wb and t.source.link == "snapshot"
    rows = tuser.get(f"/api/v1/tables/{t.id}/rows").json()["data"]["rows"]
    assert rows[0][0] == "علی" and rows[1][2] == "شیراز"


def test_deleting_the_workspace_removes_its_tables(tuser: Session) -> None:
    ws = _ws(tuser)
    t = _make(tuser, ws)
    assert tuser.delete(f"/api/v1/workspaces/{ws}?confirm=true").status_code == 204
    assert tuser.get(f"/api/v1/tables/{t.id}").status_code == 404


def test_table_to_sheet_is_undoable_and_never_overwrites(tuser: Session) -> None:
    d = Doc(tuser, "real")
    ws = tuser.get("/api/v1/workspaces").json()["data"][0]["id"]
    t = _make(tuser, ws)
    before = d.cells()
    body = {"workbook_id": d.wb, "sheet_id": d.sheet, "row": 0, "col": 5}
    r = tuser.post(f"/api/v1/tables/{t.id}/to-sheet", json=body)
    assert r.status_code == 200, r.text
    res = r.json()["data"]
    assert res["history_entry"]["seq"] == 1 and len(res["cells"]) == 8  # header + 3 rows x 2
    cells = d.cells()
    assert cells[(0, 5)]["s"] == "name" and cells[(1, 6)]["n"] == 3

    again = tuser.post(f"/api/v1/tables/{t.id}/to-sheet", json=body)  # the area is now occupied
    assert again.status_code == 409, again.text
    assert again.json()["error"]["details"][0]["code"] == "would_overwrite"
    stale = tuser.post(f"/api/v1/tables/{t.id}/to-sheet", json={**body, "col": 9, "base_seq": 0})
    assert stale.status_code == 409  # the client has not seen the entry just made

    assert d.undo().status_code == 200
    assert d.cells() == before
    assert d.redo().status_code == 200
    assert d.cells() == cells
