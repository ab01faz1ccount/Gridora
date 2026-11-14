from __future__ import annotations

import time
from typing import Any


def wait_job(client: Any, job_id: str, seconds: float = 15.0) -> dict[str, Any]:
    """Poll GET /jobs/{id} until it is finished (the dispatcher runs in the app's own loop)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        r = client.get(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200, r.text
        job = r.json()["data"]
        if job["status"] in ("succeeded", "failed"):
            return dict(job)
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in {seconds}s")


def import_csv(client: Any, workspace_id: str, name: str, data: bytes) -> dict[str, str]:
    """Upload a CSV, wait for its import job, return ids {file, job, wb, sheet}."""
    r = client.post(f"/api/v1/workspaces/{workspace_id}/files", files={"file": (name, data)})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    job = wait_job(client, d["job_id"])
    assert job["status"] == "succeeded", job
    wb = client.get(f"/api/v1/workbooks/{job['result_ref']}").json()["data"]
    return {
        "file": d["file"]["id"],
        "job": d["job_id"],
        "wb": job["result_ref"],
        "sheet": wb["sheets"][0]["id"],
    }
