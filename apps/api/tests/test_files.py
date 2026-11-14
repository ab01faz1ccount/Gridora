from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import pytest

from gridora_api.config import Settings
from gridora_api.storage.layout import StorageLayout

from .conftest import Session

XLSX = b"PK\x03\x04" + b"\x00" * 200  # ZIP signature only: type-gate tests, not an import test
CSV = "نام,مقدار\nعلی,۱۲\n".encode()


@pytest.fixture
def ws(alice: Session) -> str:
    return str(alice.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"])


def upload(s: Session, ws: str, name: str, data: bytes, field: str = "file"):  # type: ignore[no-untyped-def]
    return s.post(f"/api/v1/workspaces/{ws}/files", files={field: (name, data)})


def quarantine_files(settings: Settings) -> list[Path]:
    q = Path(settings.data_root) / "quarantine"
    return list(q.iterdir()) if q.exists() else []


# ----------------------------------------------------------------- happy path ----
def test_upload_csv_and_xlsx_are_stored_under_uuid_paths(
    alice: Session, ws: str, settings: Settings
) -> None:
    for name, data, ext in (("گزارش.csv", CSV, "csv"), ("book.xlsx", XLSX, "xlsx")):
        r = upload(alice, ws, name, data)
        assert r.status_code == 201, r.text
        rec = r.json()["data"]["file"]
        assert r.json()["data"]["job_id"]  # an import job was queued
        assert rec["kind"] == "original" and rec["display_name"] == name
        assert rec["size_bytes"] == len(data) and rec["sha256"] == hashlib.sha256(data).hexdigest()
        path = (
            Path(settings.data_root) / "users" / alice.user_id / "original" / f"{rec['id']}.{ext}"
        )
        assert path.read_bytes() == data
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert quarantine_files(settings) == []


def test_download_roundtrip_and_headers(alice: Session, ws: str) -> None:
    fid = upload(alice, ws, "گزارش فروش.csv", CSV).json()["data"]["file"]["id"]
    r = alice.get(f"/api/v1/files/{fid}/download")
    assert r.status_code == 200 and r.content == CSV
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment")
    m = re.search(r"filename\*=utf-8''([^;]+)", cd, re.IGNORECASE)
    assert m and unquote(m.group(1)) == "گزارش فروش.csv"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_hostile_filename_never_reaches_the_path(
    alice: Session, ws: str, settings: Settings
) -> None:
    r = upload(alice, ws, "../../../etc/passwd.csv", b"a\n1\n")
    assert r.status_code == 201
    assert r.json()["data"]["file"]["display_name"] == "passwd.csv"
    r = upload(alice, ws, "..\\..\\evil\\x.csv", b"a\n1\n")
    assert r.json()["data"]["file"]["display_name"] == "x.csv"
    files = [p for p in Path(settings.data_root).rglob("*") if p.is_file()]
    assert files and all(
        f.resolve().is_relative_to(Path(settings.data_root).resolve()) for f in files
    )
    assert not any(f.name.startswith(("passwd", "x.")) for f in files)


def test_upload_is_audited(alice: Session, ws: str) -> None:
    from sqlalchemy import text

    from .conftest import run_db

    upload(alice, ws, "a.csv", b"a\n1\n")

    async def q(db):  # type: ignore[no-untyped-def]
        return (await db.execute(text("select action, outcome from audit_log order by id"))).all()

    assert ("file.upload", "success") in [tuple(r) for r in run_db(q)]


# ------------------------------------------------------------------- limits ----
@pytest.fixture
def small_limit(tmp_path: Path, make_client, make_user):  # type: ignore[no-untyped-def]
    """An app whose upload cap is 2000 bytes, to test the exact boundary cheaply."""
    from gridora_api.main import create_app

    from .conftest import PASSWORD, ScanningClient, Session, fast_settings, forbidden_fragments

    s = fast_settings(tmp_path / "small", max_upload_bytes=2000)
    app = create_app(s)
    make_user("carol")
    c = ScanningClient(app, base_url="https://testserver", raise_server_exceptions=False)
    c.forbidden = forbidden_fragments(s)
    c.__enter__()
    r = c.post("/api/v1/auth/login", json={"username": "carol", "password": PASSWORD})
    sess = Session(c, "carol", r.json()["data"]["csrf_token"])
    wid = sess.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
    yield sess, wid, s
    c.__exit__(None, None, None)


def test_exact_limit_passes_and_one_byte_more_is_413(small_limit) -> None:  # type: ignore[no-untyped-def]
    sess, wid, s = small_limit
    body = b"a,b\n" + b"x" * 1996
    assert len(body) == 2000
    assert upload(sess, wid, "ok.csv", body).status_code == 201
    r = upload(sess, wid, "big.csv", body + b"y")
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert quarantine_files(s) == []  # nothing left behind
    assert len(sess.get(f"/api/v1/workspaces/{wid}/files").json()["data"]) == 1


def test_declared_content_length_over_limit_is_rejected_early(small_limit) -> None:  # type: ignore[no-untyped-def]
    sess, wid, s = small_limit
    r = sess.post(
        f"/api/v1/workspaces/{wid}/files",
        content=b"tiny",
        headers={"Content-Type": "multipart/form-data; boundary=xx", "Content-Length": "999999"},
    )
    assert r.status_code == 413
    assert quarantine_files(s) == []


def test_default_limit_is_100_mib_streamed_without_buffering(
    alice: Session, ws: str, settings: Settings
) -> None:
    limit = settings.max_upload_bytes
    assert limit == 100 * 1024 * 1024

    def body() -> Iterator[bytes]:
        yield b'--B\r\nContent-Disposition: form-data; name="file"; filename="big.csv"\r\n\r\na,b\n'
        chunk = b"x" * (1024 * 1024)
        for _ in range(100):  # 100 MiB + 4 bytes of content => 4 bytes over the limit
            yield chunk
        yield b"\r\n--B--\r\n"

    r = alice.post(
        f"/api/v1/workspaces/{ws}/files",
        content=body(),
        headers={"Content-Type": "multipart/form-data; boundary=B"},
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert quarantine_files(settings) == []


# ---------------------------------------------------------------- type gate ----
@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("fake.xlsx", b"just text, not a zip"),
        ("fake.xlsm", b"MZ\x90\x00 an exe"),
        ("bin.csv", b"a,b\x00\x01\x02\n"),
        ("utf16.csv", "a,b\n1,2\n".encode("utf-16")),
        ("empty.csv", b""),
        ("tool.exe", b"MZ"),
        ("noext", b"a,b\n"),
        ("legacy.xls", b"\xd0\xcf\x11\xe0"),
        ("page.html", b"<script>alert(1)</script>"),
    ],
)
def test_unsupported_types_are_415_and_leave_nothing(
    alice: Session, ws: str, settings: Settings, name: str, data: bytes
) -> None:
    r = upload(alice, ws, name, data)
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_media_type"
    assert quarantine_files(settings) == []
    assert alice.get(f"/api/v1/workspaces/{ws}/files").json()["data"] == []


def test_non_multipart_is_415(alice: Session, ws: str) -> None:
    r = alice.post(
        f"/api/v1/workspaces/{ws}/files", content=b"a,b", headers={"Content-Type": "text/csv"}
    )
    assert r.status_code == 415


@pytest.mark.parametrize("field", ["other", "document"])
def test_wrong_field_name_is_400(alice: Session, ws: str, field: str) -> None:
    r = upload(alice, ws, "a.csv", b"a\n", field=field)
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_two_files_are_rejected(alice: Session, ws: str, settings: Settings) -> None:
    r = alice.post(
        f"/api/v1/workspaces/{ws}/files",
        files=[("file", ("a.csv", b"a\n")), ("file", ("b.csv", b"b\n"))],
    )
    assert r.status_code == 400
    assert quarantine_files(settings) == []
    assert alice.get(f"/api/v1/workspaces/{ws}/files").json()["data"] == []


def test_truncated_multipart_leaves_nothing(alice: Session, ws: str, settings: Settings) -> None:
    r = alice.post(
        f"/api/v1/workspaces/{ws}/files",
        content=(
            b'--B\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\na,b\n1,2'
        ),
        headers={"Content-Type": "multipart/form-data; boundary=B"},
    )
    assert r.status_code in (400, 415)
    assert quarantine_files(settings) == []
    assert alice.get(f"/api/v1/workspaces/{ws}/files").json()["data"] == []


def test_upload_needs_csrf_and_a_session(alice: Session, ws: str) -> None:
    del alice.client.headers["X-CSRF-Token"]
    assert upload(alice, ws, "a.csv", b"a\n").status_code == 403


def test_ownership_checked_before_body_is_stored(
    alice: Session, bob: Session, ws: str, settings: Settings
) -> None:
    r = upload(bob, ws, "a.csv", b"a\n1\n")
    assert r.status_code == 404
    assert quarantine_files(settings) == []


# ----------------------------------------------------------------- layout ----
def test_layout_only_accepts_uuids_and_allowlisted_parts(tmp_path: Path) -> None:
    lay = StorageLayout(tmp_path)
    u = "123e4567-e89b-12d3-a456-426614174000"
    assert lay.file_key(u, "original", u, "csv") == f"users/{u}/original/{u}.csv"
    assert lay.table_path(u, u, 3) == tmp_path.resolve() / "users" / u / "tables" / u / "v3.parquet"
    for bad in ("../x", "a/b", "", "not-a-uuid", u + "/../x"):
        with pytest.raises(ValueError):
            lay.file_key(bad, "original", u, "csv")
        with pytest.raises(ValueError):
            lay.table_path(u, bad, 1)
    with pytest.raises(ValueError):
        lay.file_key(u, "original", u, "sh")
    with pytest.raises(ValueError):
        lay.file_key(u, "../etc", u, "csv")
    with pytest.raises(ValueError):
        lay.table_path(u, u, 0)
    with pytest.raises(ValueError):
        lay.resolve_key("../../etc/passwd")
