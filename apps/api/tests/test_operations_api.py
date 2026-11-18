"""Operations through the HTTP API, as jobs, on both engines (dataops: the stub operations)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from gridora_contracts.models import CellsChangedResult, OperationDescriptor, PreviewResult

from .conftest import Session
from .e2e_kit import NUM, Doc, set_cell
from .helpers import wait_job

DATA = b"k,city,qty\nb,tehran,3\na,shiraz,10\nc,tehran,2\na,tehran,7\n"


def op_body(
    d: Doc,
    type_: str,
    params: dict[str, Any],
    base_seq: int = 0,
    confirm: bool = False,
    r1: int = 4,
    c1: int = 2,
    extra: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "base_seq": base_seq,
        "confirm_destructive": confirm,
        "operation": {
            "type": type_,
            "params": params,
            "extra_targets": extra or [],
            "target": {
                "kind": "sheet_range",
                "range": {"sheet_id": d.sheet, "r0": 0, "c0": 0, "r1": r1, "c1": c1},
            },
        },
    }


def apply(d: Doc, body: dict[str, Any]) -> Any:
    return d.s.post(f"/api/v1/documents/{d.wb}/operations", json=body)


def col(d: Doc, c: int, rows: int = 5) -> list[Any]:
    cells = d.cells(rows=rows)
    return [
        (cells.get((r, c)) or {}).get("s", (cells.get((r, c)) or {}).get("n")) for r in range(rows)
    ]


SORT = {"columns": [{"column": 0}, {"column": 2, "descending": True}]}


def test_catalog_and_descriptors_are_served(user: Session) -> None:
    ds = [
        OperationDescriptor.model_validate(x) for x in user.get("/api/v1/operations").json()["data"]
    ]
    assert {d.type for d in ds} == {"sort", "find_replace", "remove_duplicates"}
    fa = user.get("/api/v1/operations/i18n?locale=fa").json()["data"]
    en = user.get("/api/v1/operations/i18n?locale=en").json()["data"]
    assert set(fa) == set(en) and fa["ops.sort.label"] != en["ops.sort.label"]
    for d in ds:
        assert d.label in fa and d.description in fa
    assert user.get("/api/v1/operations/i18n?locale=../x").status_code == 400


def test_preview_changes_nothing(user: Session, kind: str) -> None:
    d = Doc(user, kind, DATA)
    before = d.cells()
    r = d.s.post(
        f"/api/v1/documents/{d.wb}/operations/preview", json=op_body(d, "sort", SORT)["operation"]
    )
    assert r.status_code == 200, r.text
    p = PreviewResult.model_validate(r.json()["data"])
    assert p.total_rows == 4 and len(p.rows) >= 4
    assert d.cells() == before and d.history().json()["data"] == []


def test_sort_is_a_job_with_history_and_undo(user: Session, kind: str) -> None:
    d = Doc(user, kind, DATA)
    start = col(d, 0)
    r = apply(d, op_body(d, "sort", SORT))
    assert r.status_code == 200, r.text  # finished within the inline window
    res = CellsChangedResult.model_validate(r.json()["data"])
    assert res.history_entry.label == "ops.sort.label" and res.history_entry.seq == 1
    assert res.history_entry.operation.type == "sort" and res.sheet_id == d.sheet
    assert col(d, 0) == ["k", "a", "a", "b", "c"]  # header kept, rows ordered
    assert col(d, 2)[1:3] == [10.0, 7.0]  # second key descending
    # the job exists and says what it produced
    jobs = [j for j in _all_jobs(user, d)]
    assert jobs and jobs[0]["kind"] == "operation" and jobs[0]["status"] == "succeeded"
    assert d.undo().status_code == 200 and col(d, 0) == start
    assert d.redo().status_code == 200 and col(d, 0) == ["k", "a", "a", "b", "c"]


def _all_jobs(s: Session, d: Doc) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from .conftest import run_db

    async def q(db: Any) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                text(
                    "select id::text, kind, status, result_ref from jobs "
                    "where kind='operation' order by created_at"
                )
            )
        ).all()
        return [{"id": a, "kind": b, "status": c, "result_ref": e} for a, b, c, e in rows]

    return run_db(q)


# ---------------------------------------------------------------- safety checks ----
def test_destructive_operations_need_confirmation(user: Session, kind: str) -> None:
    d = Doc(user, kind, DATA)
    before = d.cells()
    body = op_body(d, "find_replace", {"find": "tehran", "replace": "Tehran"})
    r = apply(d, body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "operation_conflict"
    assert r.json()["error"]["details"][0]["code"] == "operation.confirm_required"
    assert d.cells() == before and d.history().json()["data"] == []
    body["confirm_destructive"] = True
    assert apply(d, body).status_code == 200
    assert col(d, 1)[1] == "Tehran"


def test_validation_errors_come_back_as_json_pointers(user: Session, kind: str) -> None:
    d = Doc(user, kind, DATA)
    r = apply(d, op_body(d, "sort", {"columns": [{"column": 9}]}))
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"
    assert r.json()["error"]["details"][0]["path"] == "/params/columns/0/column"
    r = apply(d, op_body(d, "no_such_op", {}))
    assert r.status_code == 400 and r.json()["error"]["details"][0]["path"] == "/type"
    assert d.history().json()["data"] == []


def test_a_stale_base_seq_is_refused(user: Session, kind: str) -> None:
    d = Doc(user, kind, DATA)
    r = apply(d, op_body(d, "sort", SORT, base_seq=3))
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_conflict"


def test_every_target_must_belong_to_the_user(
    user: Session,
    kind: str,
    eapp: FastAPI,
    make_user: Any,
) -> None:
    d = Doc(user, kind, DATA)
    # a sheet id that exists nowhere
    body = op_body(d, "sort", SORT)
    body["operation"]["target"]["range"]["sheet_id"] = "00000000-0000-0000-0000-0000000000ff"
    assert apply(d, body).status_code == 404
    # an extra target pointing at a sheet that nobody owns
    ghost = {
        "kind": "sheet_range",
        "range": {"sheet_id": "no-such-sheet", "r0": 0, "c0": 0, "r1": 1, "c1": 1},
    }
    assert apply(d, op_body(d, "sort", SORT, extra=[ghost])).status_code == 404
    assert d.history().json()["data"] == []


def test_cannot_use_another_users_sheet_as_an_extra_target(
    eapp: FastAPI,
    kind: str,
    tmp_path: Any,
    make_user: Any,
) -> None:
    from .conftest import PASSWORD, ScanningClient, fast_settings, forbidden_fragments

    make_user("user1")
    make_user("user2")
    fs = forbidden_fragments(fast_settings(tmp_path / kind))
    c1 = ScanningClient(eapp, base_url="https://testserver", raise_server_exceptions=False)
    c1.forbidden = fs
    c1.__enter__()
    try:
        s1 = Session(
            c1,
            "u1",
            c1.post("/api/v1/auth/login", json={"username": "user1", "password": PASSWORD}).json()[
                "data"
            ]["csrf_token"],
        )
        c2 = ScanningClient(eapp, base_url="https://testserver", raise_server_exceptions=False)
        c2.forbidden = fs
        s2 = Session(
            c2,
            "u2",
            c2.post("/api/v1/auth/login", json={"username": "user2", "password": PASSWORD}).json()[
                "data"
            ]["csrf_token"],
        )
        d1, d2 = Doc(s1, kind, DATA), Doc(s2, kind, DATA)
        foreign = {
            "kind": "sheet_range",
            "range": {"sheet_id": d1.sheet, "r0": 0, "c0": 0, "r1": 1, "c1": 1},
        }
        r = apply(d2, op_body(d2, "sort", SORT, extra=[foreign]))
        assert r.status_code == 404  # u2 cannot reach u1's sheet through an extra target
        assert d2.history().json()["data"] == []
    finally:
        c1.__exit__(None, None, None)


# ----------------------------------------------------------------------- jobs ----
def test_a_slow_operation_answers_202_and_finishes_as_a_job(
    user: Session,
    kind: str,
    eapp: FastAPI,
) -> None:
    d = Doc(user, kind, DATA)
    eapp.state.settings.operation_inline_seconds = 0.2
    real_apply = eapp.state.services.executor.apply

    def slow(op: Any, ctx: Any) -> Any:
        time.sleep(1.2)
        return real_apply(op, ctx)

    eapp.state.services.executor.apply = slow
    t0 = time.monotonic()
    r = apply(d, op_body(d, "sort", SORT))
    assert r.status_code == 202 and time.monotonic() - t0 < 1.0  # the request did NOT wait for it
    job = r.json()["data"]
    assert job["kind"] == "operation" and job["status"] in ("queued", "running")
    done = wait_job(user, job["id"], 20)
    assert done["status"] == "succeeded" and done["result_ref"] == "1"  # the history seq it created
    assert col(d, 0) == ["k", "a", "a", "b", "c"]
    assert [e["seq"] for e in d.history().json()["data"]] == [1]


def test_a_failing_job_reports_the_same_typed_error(
    user: Session,
    kind: str,
    eapp: FastAPI,
) -> None:
    d = Doc(user, kind, DATA)
    eapp.state.settings.operation_inline_seconds = 0
    r = apply(d, op_body(d, "sort", {"columns": [{"column": 9}]}))
    assert r.status_code == 202  # validated inside the job (data-dependent checks run there)
    job = wait_job(user, r.json()["data"]["id"], 20)
    assert job["status"] == "failed" and job["error"]["code"] == "validation_failed"
    assert job["error"]["details"][0]["path"] == "/params/columns/0/column"
    assert d.history().json()["data"] == []


def test_an_operation_and_an_edit_never_interleave(
    user: Session,
    kind: str,
    eapp: FastAPI,
) -> None:
    import concurrent.futures

    from .conftest import ScanningClient

    d = Doc(user, kind, DATA)
    cs = []
    for _ in range(2):
        c = ScanningClient(eapp, base_url="https://testserver", raise_server_exceptions=False)
        c.cookies.update(user.client.cookies)
        c.headers["X-CSRF-Token"] = user.client.headers["X-CSRF-Token"]
        cs.append(c)

    def run_op() -> int:
        return int(
            cs[0]
            .post(f"/api/v1/documents/{d.wb}/operations", json=op_body(d, "sort", SORT))
            .status_code
        )

    def run_edit() -> int:
        return int(
            cs[1]
            .patch(
                f"/api/v1/workbooks/{d.wb}/sheets/{d.sheet}/cells",
                json={"base_seq": 0, "edits": [set_cell(1, 2, NUM(99))]},
            )
            .status_code
        )

    with concurrent.futures.ThreadPoolExecutor(2) as ex:
        codes = sorted([ex.submit(run_op).result(), ex.submit(run_edit).result()])
    assert codes in ([200, 409], [200, 200]) and codes[0] == 200
    entries = d.history().json()["data"]
    assert len(entries) == (2 if codes == [200, 200] else 1)  # no lost or duplicated entry


# ---------------------------------------------------------------- history cap ----
def test_a_change_too_big_to_undo_is_refused_with_a_typed_error(user: Session, kind: str) -> None:
    d = Doc(user, kind, DATA)
    before = d.cells()
    # 600 x 400 = 240,000 cells > the 200,000-cell undo cap
    r = apply(d, op_body(d, "sort", {"columns": [{"column": 0}]}, r1=599, c1=399))
    if r.status_code == 202:
        job = wait_job(user, r.json()["data"]["id"], 60)
        err = job["error"]
    else:
        err = r.json()["error"]
    assert err["code"] == "operation_conflict"
    assert err["details"][0]["code"] == "too_large_for_history"
    assert d.cells() == before and d.history().json()["data"] == []
