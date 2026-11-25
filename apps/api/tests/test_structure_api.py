"""Insert / delete rows and columns through the API (real engine) and its absence (stub engine)."""

from __future__ import annotations

from .conftest import Session
from .e2e_kit import NUM, Doc


def _structure(d: Doc, axis: str, op: str, at: int, count: int, base_seq: int):
    return d.s.post(
        f"/api/v1/workbooks/{d.wb}/sheets/{d.sheet}/structure",
        json={"base_seq": base_seq, "axis": axis, "op": op, "at": at, "count": count},
    )


def test_insert_delete_and_undo_redo(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    r = _structure(d, "row", "insert", 1, 2, 0)
    if kind == "stub":
        assert r.status_code == 409
        assert r.json()["error"]["details"][0]["code"] == "engine.not_implemented"
        return
    assert r.status_code == 200, r.text
    assert r.json()["data"]["history_entry"]["delta"]["kind"] == "sheet_structure"
    before = d.cells()
    assert (0, 0) in before and (1, 0) not in before and (2, 0) not in before and (3, 0) in before

    meta = user.get(f"/api/v1/workbooks/{d.wb}").json()["data"]["sheets"][0]
    assert meta["row_count"] >= 5

    u = user.post(f"/api/v1/documents/{d.wb}/undo?base_seq=1")
    assert u.status_code == 200, u.text
    assert (1, 0) in d.cells() and (3, 0) not in d.cells()
    rd = user.post(f"/api/v1/documents/{d.wb}/redo?base_seq=0")
    assert rd.status_code == 200, rd.text
    assert d.cells() == before

    # a delete is one entry as well, and its undo brings the deleted cells back
    e = d.edit([{"r": 0, "c": 5, "value": NUM(7)}], base_seq=1)
    assert e.status_code == 200, e.text
    r2 = _structure(d, "col", "delete", 5, 1, 2)
    assert r2.status_code == 200, r2.text
    assert (0, 5) not in d.cells()
    user.post(f"/api/v1/documents/{d.wb}/undo?base_seq=3")
    assert d.cells()[(0, 5)] == NUM(7)


def test_validation_and_stale_base(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    assert _structure(d, "row", "insert", 0, 0, 0).status_code == 400  # count >= 1
    assert _structure(d, "diag", "insert", 0, 1, 0).status_code == 400  # axis
    if kind == "real":
        assert _structure(d, "row", "insert", 0, 1, 99).status_code == 409  # stale base_seq


def test_history_replays_after_the_working_copy_is_dropped(user: Session, kind: str, eapp) -> None:
    if kind == "stub":
        return
    d = Doc(user, kind)
    assert _structure(d, "row", "insert", 0, 1, 0).status_code == 200
    assert _structure(d, "col", "insert", 0, 2, 1).status_code == 200
    expected = d.cells()
    eapp.state.copies.drop(d.wb)  # reopen from the stored file + committed history
    assert d.cells() == expected
    assert (1, 2) in expected and (0, 0) not in expected
