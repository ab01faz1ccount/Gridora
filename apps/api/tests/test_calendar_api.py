"""Calendar endpoints (contract 0.6.0): date-column detection and the per-workbook calendar option,
on BOTH engines. The 'real' variant is skipped when packages/engine is not installed."""

from __future__ import annotations

from gridora_contracts.models import DateColumns, Workbook

from .conftest import Session
from .e2e_kit import Doc


def test_date_columns_endpoint_returns_a_typed_list(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    r = user.get(f"/api/v1/workbooks/{d.wb}/sheets/{d.sheet}/date-columns")
    assert r.status_code == 200, r.text
    res = DateColumns.model_validate(r.json()["data"])
    assert res.sheet_id == d.sheet  # the public sheet id, never the engine's
    assert isinstance(res.columns, list)


def test_unknown_sheet_is_not_found(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    r = user.get(f"/api/v1/workbooks/{d.wb}/sheets/nope/date-columns")
    assert r.status_code == 404


def test_set_calendar_persists_and_is_not_an_edit(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    first = Workbook.model_validate(user.get(f"/api/v1/workbooks/{d.wb}").json()["data"])
    assert first.calendar == "jalali"
    r = user.put(f"/api/v1/workbooks/{d.wb}/calendar", json={"calendar": "hijri"})
    assert r.status_code == 200, r.text
    assert Workbook.model_validate(r.json()["data"]).calendar == "hijri"
    got = Workbook.model_validate(user.get(f"/api/v1/workbooks/{d.wb}").json()["data"])
    assert got.calendar == "hijri"
    assert d.history().json()["data"] == []  # a view option: nothing to undo


def test_set_calendar_rejects_unknown_values(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    r = user.put(f"/api/v1/workbooks/{d.wb}/calendar", json={"calendar": "mayan"})
    assert r.status_code == 400
