"""Export (a job that makes a downloadable file) and save (a new workbook version), end to end."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from gridora_contracts.models import CompatibilityReport, FileRecord, Job

from .conftest import Session
from .e2e_kit import NUM, Doc, set_cell
from .helpers import wait_job


def _export(user: Session, d: Doc, body: dict[str, str]) -> Job:
    r = user.post(f"/api/v1/workbooks/{d.wb}/export", json=body)
    assert r.status_code == 202, r.text
    job = wait_job(user, r.json()["data"]["id"])
    return Job.model_validate(job)


def test_csv_export_gives_a_downloadable_file_and_a_report(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    job = _export(user, d, {"format": "csv", "sheet_id": d.sheet})
    assert job.kind == "export" and job.status == "succeeded", job
    assert job.result_ref
    dl = user.get(f"/api/v1/files/{job.result_ref}/download")
    assert dl.status_code == 200
    text = dl.content.decode("utf-8-sig")
    assert "تعداد" in text and "شیراز" in text
    rep = user.get(f"/api/v1/jobs/{job.id}/compatibility")
    assert rep.status_code == 200, rep.text
    CompatibilityReport.model_validate(rep.json()["data"])


def test_csv_export_needs_a_valid_sheet(user: Session, kind: str) -> None:
    d = Doc(user, kind)
    for body in ({"format": "csv"}, {"format": "csv", "sheet_id": "nope"}):
        r = user.post(f"/api/v1/workbooks/{d.wb}/export", json=body)
        assert r.status_code == 400, r.text
    assert user.post(f"/api/v1/workbooks/{d.wb}/export", json={"format": "pdf"}).status_code == 400


def test_xlsx_export_and_save(user: Session, kind: str) -> None:
    if kind == "stub":
        pytest.skip("XLSX needs the real engine")
    d = Doc(user, kind)
    job = _export(user, d, {"format": "xlsx"})
    assert job.status == "succeeded" and job.result_ref
    dl = user.get(f"/api/v1/files/{job.result_ref}/download")
    assert dl.content[:2] == b"PK"  # a zip container

    r = user.post(f"/api/v1/workbooks/{d.wb}/save")
    assert r.status_code == 200, r.text
    rec = FileRecord.model_validate(r.json()["data"])
    assert rec.kind == "workbook" and rec.display_name.endswith(".xlsx") and rec.parent_id


def test_save_bakes_history_in_and_undo_still_works_after_a_rebuild(
    user: Session, eapp: FastAPI, kind: str
) -> None:
    if kind == "stub":
        pytest.skip("XLSX needs the real engine")
    d = Doc(user, kind)
    start = d.cells()
    assert d.edit([set_cell(1, 1, NUM(30))], 0).status_code == 200
    edited = d.cells()
    assert user.post(f"/api/v1/workbooks/{d.wb}/save").status_code == 200
    eapp.state.copies.drop(d.wb)  # force a rebuild: the workbook reopens from the saved version
    assert d.cells() == edited
    assert d.undo().status_code == 200
    assert d.cells() == start
    assert d.redo().status_code == 200
    assert d.cells() == edited
