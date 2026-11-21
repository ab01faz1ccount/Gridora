"""End to end through the HTTP API: upload -> window -> edit -> undo/redo -> rebuild, on BOTH
engines. The 'real' variant is skipped when packages/engine is not installed (and says so)."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from gridora_contracts.models import CellsChangedResult, HistoryEntry

from .conftest import ScanningClient, Session
from .e2e_kit import NUM, STR, Doc, set_cell
from .helpers import wait_job


# ------------------------------------------------------------------- the slice ----
def test_upload_window_edit_undo_redo(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    start = d.cells()
    assert start[(1, 1)] == NUM(3.0) and start[(2, 2)] == STR("شیراز")

    r = d.edit([set_cell(1, 1, NUM(30)), set_cell(2, 2, STR("اصفهان"))])
    assert r.status_code == 200, r.text
    res = CellsChangedResult.model_validate(r.json()["data"])
    assert res.history_entry.seq == 1 and res.history_entry.label == "history.cell_edit"
    assert res.sheet_id == d.sheet and not res.history_entry.undone
    assert {(c.r, c.c) for c in res.cells} == {(1, 1), (2, 2)}  # the changed cells (delta.after)
    after_edit = d.cells()
    assert after_edit[(1, 1)] == NUM(30.0) and after_edit[(2, 2)] == STR("اصفهان")

    u = d.undo()
    assert u.status_code == 200, u.text
    undone = CellsChangedResult.model_validate(u.json()["data"])
    assert undone.history_entry.undone and {(c.r, c.c) for c in undone.cells} == {(1, 1), (2, 2)}
    assert d.cells() == start  # exactly the original state

    rd = d.redo()
    assert rd.status_code == 200 and not rd.json()["data"]["history_entry"]["undone"]
    assert d.cells() == after_edit


def test_a_new_edit_after_undo_discards_redo_and_seq_never_repeats(
    user: Session, kind: str
) -> None:
    d = Doc(user, kind)
    assert d.edit([set_cell(1, 1, NUM(10))], 0).json()["data"]["history_entry"]["seq"] == 1
    assert d.undo().status_code == 200
    r = d.edit([set_cell(1, 1, NUM(20))], 0)  # head is 0 after the undo
    assert r.status_code == 200 and r.json()["data"]["history_entry"]["seq"] == 2  # not 1 again
    red = d.redo()
    assert red.status_code == 409
    assert red.json()["error"]["details"][0]["code"] == "history.nothing_to_redo"
    entries = [HistoryEntry.model_validate(e) for e in d.history().json()["data"]]
    assert [e.seq for e in entries] == [2]  # the undone entry is gone
    stale = d.edit([set_cell(0, 0, NUM(1))], base_seq=1)  # a tab that saw the old entry
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"


def test_nothing_to_undo(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    r = d.undo()
    assert r.status_code == 409 and r.json()["error"]["code"] == "operation_conflict"
    assert r.json()["error"]["details"][0]["code"] == "history.nothing_to_undo"


# ------------------------------------------------------------------ concurrency ----
def test_a_stale_base_seq_changes_nothing(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    before = d.cells()
    r = d.edit([set_cell(1, 1, NUM(99))], base_seq=7)
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_conflict"
    assert r.json()["error"]["details"][0]["code"] == "history.stale"
    assert d.cells() == before and d.history().json()["data"] == []


def test_simultaneous_edits_with_the_same_base_only_one_wins(
    user: Session, kind: str, eapp: FastAPI
) -> None:
    d = Doc(user, kind)
    clients = []
    for _ in range(6):
        c = ScanningClient(eapp, base_url="https://testserver", raise_server_exceptions=False)
        c.cookies.update(user.client.cookies)
        c.headers["X-CSRF-Token"] = user.client.headers["X-CSRF-Token"]
        clients.append(c)

    def go(i: int) -> int:
        return int(
            clients[i]
            .patch(
                f"/api/v1/workbooks/{d.wb}/sheets/{d.sheet}/cells",
                json={"base_seq": 0, "edits": [set_cell(1, 1, NUM(100 + i))]},
            )
            .status_code
        )

    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        codes = sorted(ex.map(go, range(6)))
    assert codes == [200, 409, 409, 409, 409, 409]
    assert len(d.history().json()["data"]) == 1


# ---------------------------------------------------------------------- atomic ----
def test_a_bad_edit_in_a_batch_applies_nothing(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    before = d.cells()
    # the stub has no formulas; the real engine has, but it has Excel's sheet limits
    bad = {"r": 2, "c": 2, "formula": "=1+1"} if kind == "stub" else set_cell(2_000_000, 0, NUM(1))
    r = d.edit([set_cell(1, 1, NUM(5)), bad])
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"
    assert d.cells() == before  # the first, valid edit was not kept
    assert d.history().json()["data"] == []


@pytest.mark.parametrize("edits", [[], [{"r": -1, "c": 0, "value": {"k": "num", "n": 1}}]])
def test_malformed_edit_requests_are_400(user: Session, kind: str, edits: list[Any]) -> None:
    assert Doc(user, kind).edit(edits).status_code == 400


def test_an_edit_past_the_end_grows_the_sheet(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    assert d.edit([set_cell(50, 7, STR("far"))]).status_code == 200
    sheet = user.get(f"/api/v1/workbooks/{d.wb}").json()["data"]["sheets"][0]
    assert sheet["row_count"] >= 51 and sheet["col_count"] >= 8
    assert d.cells(rows=60, cols=10)[(50, 7)] == STR("far")


def test_clearing_a_cell_is_an_edit_too(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    assert d.edit([set_cell(1, 0, None)]).status_code == 200
    assert (1, 0) not in d.cells()
    d.undo()
    assert d.cells()[(1, 0)] == STR("علی")


# --------------------------------------------------------------------- rebuild ----
def test_rebuilding_after_a_restart_gives_the_same_cells_and_undo_still_works(
    user: Session, kind: str, eapp: FastAPI
) -> None:
    d = Doc(user, kind)
    d.edit([set_cell(1, 1, NUM(11))])
    d.edit([set_cell(2, 2, STR("بعدی"))], base_seq=1)
    d.edit([set_cell(0, 0, STR("سرتیتر"))], base_seq=2)
    d.undo()  # the third edit is undone: it must NOT come back on rebuild
    live = d.cells()

    eapp.state.copies.close_all()  # what a restart or eviction does
    assert not eapp.state.copies.is_open(d.wb)
    assert d.cells() == live  # same data; the engine got NEW sheet ids, the URL keeps the old one
    assert d.cells()[(0, 0)] == STR("نام")  # undone edit stayed undone

    assert d.undo().status_code == 200  # undo works on the rebuilt copy
    assert d.cells()[(2, 2)] == STR("شیراز")
    assert d.redo().status_code == 200 and d.redo().status_code == 200
    assert d.cells()[(0, 0)] == STR("سرتیتر")


def test_history_listing_is_paged_newest_first(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    for i in range(5):
        assert d.edit([set_cell(1, 1, NUM(i))], base_seq=i).status_code == 200
    first = d.history("?limit=2").json()
    assert [e["seq"] for e in first["data"]] == [5, 4]
    nxt = first["meta"]["next_cursor"]
    second = d.history(f"?limit=2&cursor={nxt}").json()
    assert [e["seq"] for e in second["data"]] == [3, 2]
    last = d.history(f"?limit=2&cursor={second['meta']['next_cursor']}").json()
    assert [e["seq"] for e in last["data"]] == [1] and last["meta"].get("next_cursor") is None
    assert d.history("?limit=0").status_code == 400
    assert d.history("?cursor=abc").status_code == 400


def test_history_entry_is_contract_shaped_and_has_no_internals(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    d.edit([set_cell(1, 1, NUM(7))])
    e = d.history().json()["data"][0]
    assert set(e) == set(HistoryEntry.model_fields)
    assert e["operation"]["type"] == "cell_edit" and e["delta"]["kind"] == "cell_patch"
    assert e["delta"]["sheet_id"] == d.sheet  # public sheet id, not the engine's


# ------------------------------------------------------------------ real engine ----
def test_real_engine_reads_a_real_xlsx_edits_and_undoes_it(
    user: Session, kind: str, eapp: FastAPI
) -> None:
    if kind != "real":
        pytest.skip("XLSX needs the real engine")
    src = Path(__file__).resolve().parents[3] / "corpus" / "apache-poi" / "45544.xlsx"
    if not src.exists():
        pytest.skip("corpus file not present")
    ws = user.post("/api/v1/workspaces", json={"name": "x"}).json()["data"]["id"]
    up = user.post(
        f"/api/v1/workspaces/{ws}/files", files={"file": ("book.xlsx", src.read_bytes())}
    )
    assert up.status_code == 201
    job = wait_job(user, up.json()["data"]["job_id"], 60)
    assert job["status"] == "succeeded", job
    wb_id = job["result_ref"]
    wb = user.get(f"/api/v1/workbooks/{wb_id}").json()["data"]
    assert wb["compat"]["items"][0]["code"] != "stub.engine"  # a real report, not the stub's
    sheet = wb["sheets"][0]["id"]
    q = f"/api/v1/workbooks/{wb_id}/sheets/{sheet}/cells?r0=0&c0=0&rows=20&cols=10"
    before = user.get(q).json()["data"]["cells"]
    r = user.patch(
        f"/api/v1/workbooks/{wb_id}/sheets/{sheet}/cells",
        json={"base_seq": 0, "edits": [set_cell(0, 0, STR("edited"))]},
    )
    assert r.status_code == 200, r.text
    assert user.post(f"/api/v1/documents/{wb_id}/undo").status_code == 200
    assert user.get(q).json()["data"]["cells"] == before
    eapp.state.copies.close_all()  # rebuild from the XLSX with a fresh engine state
    assert user.get(q).json()["data"]["cells"] == before


def test_real_engine_validation_errors_reach_the_client_typed(user: Session, kind: str) -> None:
    if kind != "real":
        pytest.skip("the stub has no Excel limits")
    d = Doc(user, kind)
    r = d.edit([set_cell(2_000_000, 0, NUM(1))])  # past Excel's 1,048,576 rows
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"
    assert r.json()["error"]["details"][0]["code"]  # the engine's stable reason
    assert d.history().json()["data"] == []
    assert user.get("/readyz").headers.get("x-gridora-engine") == "real"


def test_which_engine_is_running_is_visible(user: Session, kind: str) -> None:
    assert user.get("/api/v1/auth/me").headers["x-gridora-engine"] == kind
