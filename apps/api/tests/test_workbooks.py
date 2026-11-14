from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from gridora_contracts.models import CellWindow, CompatibilityReport, Job, Workbook

from .conftest import Session, fast_settings
from .helpers import import_csv, wait_job

CSV = "نام,تعداد,شهر\nعلی,3,تهران\nرضا,4.5,شیراز\n".encode()


@pytest.fixture
def ws(alice: Session) -> str:
    return str(alice.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"])


def cells(s: Session, ids: dict[str, str], q: str = "r0=0&c0=0&rows=10&cols=10") -> Any:
    return s.get(f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/cells?{q}")


def test_upload_import_job_open_and_read_cells(alice: Session, ws: str) -> None:
    ids = import_csv(alice, ws, "فروش.csv", CSV)
    job = Job.model_validate(alice.get(f"/api/v1/jobs/{ids['job']}").json()["data"])
    assert job.kind == "import" and job.status == "succeeded" and job.progress == 1.0
    assert job.result_ref == ids["wb"] and job.error is None

    wb = Workbook.model_validate(alice.get(f"/api/v1/workbooks/{ids['wb']}").json()["data"])
    assert wb.id == ids["wb"] and wb.file_id == ids["file"]  # the API owns the ids
    assert wb.name == "فروش.csv"
    assert [(s.name, s.row_count, s.col_count) for s in wb.sheets] == [("Sheet1", 3, 3)]

    r = cells(alice, ids)
    assert r.status_code == 200
    cw = CellWindow.model_validate(r.json()["data"])
    by = {(c.r, c.c): c.v.model_dump() for c in cw.cells if c.v}
    assert by[(0, 0)] == {"k": "str", "s": "نام"}
    assert by[(1, 1)] == {"k": "num", "n": 3.0}
    assert by[(2, 2)] == {"k": "str", "s": "شیراز"}
    assert len(cw.cells) == 9


def test_compatibility_report_is_honest_about_the_stub(alice: Session, ws: str) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a\n1\n")
    rep = CompatibilityReport.model_validate(
        alice.get(f"/api/v1/workbooks/{ids['wb']}/compatibility").json()["data"]
    )
    assert rep.items[0].code == "stub.engine" and rep.items[0].status == "partial"
    assert rep.summary.partial == 1


def test_open_is_idempotent_and_returns_the_same_workbook(alice: Session, ws: str) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a,b\n1,2\n")
    a = alice.post(f"/api/v1/files/{ids['file']}/open")
    b = alice.post(f"/api/v1/files/{ids['file']}/open")
    assert a.status_code == b.status_code == 200
    assert a.json()["data"]["id"] == b.json()["data"]["id"] == ids["wb"]
    assert a.json()["data"]["compat"]["items"][0]["code"] == "stub.engine"


# ------------------------------------------------------------------ windows ----
def test_window_clipping_and_offsets(alice: Session, ws: str) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a,b,c\n1,2,3\n4,5,6\n")
    cw = cells(alice, ids, "r0=1&c0=1&rows=1&cols=2").json()["data"]
    assert [(c["r"], c["c"]) for c in cw["cells"]] == [(1, 1), (1, 2)]
    far = cells(alice, ids, "r0=500&c0=0&rows=10&cols=10").json()["data"]
    assert far["cells"] == []  # empty window, not an error


@pytest.mark.parametrize(
    "q",
    [
        "r0=0&c0=0&rows=1001&cols=1",  # over the contract row cap
        "r0=0&c0=0&rows=1&cols=101",  # over the column cap
        "r0=-1&c0=0&rows=1&cols=1",
        "r0=0&c0=0&rows=0&cols=1",
        "r0=0&c0=0&rows=1",  # missing parameter
        "r0=x&c0=0&rows=1&cols=1",
    ],
)
def test_window_limits_are_enforced(alice: Session, ws: str, q: str) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a\n1\n")
    r = cells(alice, ids, q)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"


def test_exact_window_cap_is_allowed(alice: Session, ws: str) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a\n1\n")
    assert cells(alice, ids, "r0=0&c0=0&rows=1000&cols=100").status_code == 200


def test_unknown_sheet_and_malformed_ids_are_404(alice: Session, ws: str) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a\n1\n")
    q = "r0=0&c0=0&rows=1&cols=1"
    assert alice.get(f"/api/v1/workbooks/{ids['wb']}/sheets/nope/cells?{q}").status_code == 404
    assert alice.get(f"/api/v1/workbooks/not-a-uuid/sheets/x/cells?{q}").status_code == 404
    assert alice.get("/api/v1/workbooks/00000000-0000-0000-0000-000000000000").status_code == 404


def test_a_lower_configured_window_cap_wins(tmp_path: Any, make_user: Any) -> None:
    from fastapi.testclient import TestClient

    from gridora_api.main import create_app

    from .conftest import PASSWORD, ScanningClient, forbidden_fragments

    s = fast_settings(tmp_path / "w", max_window_rows=10)
    make_user("dora")
    with ScanningClient(
        create_app(s), base_url="https://testserver", raise_server_exceptions=False
    ) as c:
        c.forbidden = forbidden_fragments(s)
        tok = c.post("/api/v1/auth/login", json={"username": "dora", "password": PASSWORD})
        sess = Session(c, "dora", tok.json()["data"]["csrf_token"])
        w = sess.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
        ids = import_csv(sess, w, "a.csv", b"a\n1\n")
        assert cells(sess, ids, "r0=0&c0=0&rows=10&cols=1").status_code == 200
        assert cells(sess, ids, "r0=0&c0=0&rows=11&cols=1").status_code == 400
    _ = TestClient


# ------------------------------------------------------- failures are honest ----
def test_xlsx_import_fails_cleanly_with_the_stub(alice: Session, ws: str) -> None:
    up = alice.post(
        f"/api/v1/workspaces/{ws}/files", files={"file": ("b.xlsx", b"PK\x03\x04" + b"\0" * 50)}
    ).json()["data"]
    job = wait_job(alice, up["job_id"])
    assert job["status"] == "failed" and job["result_ref"] is None
    assert job["error"]["code"] == "unsupported_workbook"
    assert job["error"]["details"][0]["code"] == "stub.xlsx_unsupported"
    assert job["error"]["request_id"]  # the originating request id is kept
    # the original is kept and downloadable; there is just no workbook
    assert alice.get(f"/api/v1/files/{up['file']['id']}/download").status_code == 200
    r = alice.post(f"/api/v1/files/{up['file']['id']}/open")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_workbook"


def test_engine_crash_is_a_generic_internal_error(alice: Session, ws: str, app: FastAPI) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("secret /srv/gridora/users/x password=hunter2")

    app.state.services.engine.import_csv = boom
    up = alice.post(f"/api/v1/workspaces/{ws}/files", files={"file": ("a.csv", b"a\n1\n")})
    job = wait_job(alice, up.json()["data"]["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert "secret" not in str(job) and "hunter2" not in str(job)


def test_slow_import_times_out_as_import_failed(alice: Session, ws: str, app: FastAPI) -> None:
    import time

    app.state.settings.import_timeout_seconds = 0.2
    real = app.state.services.engine.import_csv

    def slow(*a: Any, **k: Any) -> Any:
        time.sleep(1.0)
        return real(*a, **k)

    app.state.services.engine.import_csv = slow
    up = alice.post(f"/api/v1/workspaces/{ws}/files", files={"file": ("a.csv", b"a\n1\n")})
    job = wait_job(alice, up.json()["data"]["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "import_failed"


# ------------------------------------------------------- working copy cache ----
def test_cells_survive_a_restart_or_eviction_with_stable_ids(
    alice: Session, ws: str, app: FastAPI
) -> None:
    ids = import_csv(alice, ws, "a.csv", b"a,b\n1,2\n")
    before = cells(alice, ids).json()["data"]
    app.state.copies.close_all()  # what a restart or eviction does
    assert not app.state.copies.is_open(ids["wb"])
    after = cells(alice, ids)
    assert after.status_code == 200 and after.json()["data"] == before  # same sheet id, same data
    assert app.state.copies.is_open(ids["wb"])


def test_lru_cap_evicts_and_reloads(tmp_path: Any, make_user: Any) -> None:
    from gridora_api.main import create_app

    from .conftest import PASSWORD, ScanningClient, forbidden_fragments

    s = fast_settings(tmp_path / "lru", max_open_workbooks=2)
    app = create_app(s)
    make_user("erin")
    with ScanningClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        c.forbidden = forbidden_fragments(s)
        tok = c.post("/api/v1/auth/login", json={"username": "erin", "password": PASSWORD})
        sess = Session(c, "erin", tok.json()["data"]["csrf_token"])
        w = sess.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
        docs = [import_csv(sess, w, f"f{i}.csv", f"v\n{i}\n".encode()) for i in range(4)]
        assert len(app.state.copies) == 2  # never more than the cap when nothing is busy
        assert not app.state.copies.is_open(docs[0]["wb"])  # oldest were evicted
        for i, ids in enumerate(docs):  # every workbook is still readable
            got = cells(sess, ids).json()["data"]["cells"]
            assert [x["v"]["n"] for x in got if x["r"] == 1] == [float(i)]
        assert len(app.state.copies) == 2


def test_workspace_delete_removes_workbooks_and_closes_copies(
    alice: Session, ws: str, app: FastAPI
) -> None:
    from sqlalchemy import text

    from .conftest import run_db

    ids = import_csv(alice, ws, "a.csv", b"a\n1\n")
    assert app.state.copies.is_open(ids["wb"])
    assert alice.delete(f"/api/v1/workspaces/{ws}?confirm=true").status_code == 204
    assert not app.state.copies.is_open(ids["wb"])
    assert alice.get(f"/api/v1/workbooks/{ids['wb']}").status_code == 404

    async def counts(db: Any) -> list[int]:
        docs = (await db.execute(text("select count(*) from documents"))).scalar_one()
        wbs = (await db.execute(text("select count(*) from workbooks"))).scalar_one()
        return [docs, wbs]

    assert run_db(counts) == [0, 0]
