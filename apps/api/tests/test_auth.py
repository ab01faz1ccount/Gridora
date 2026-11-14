from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gridora_contracts.models import AuthResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gridora_api.config import Settings
from gridora_api.main import create_app

from .conftest import PASSWORD, fast_settings, run_db
from .routes import implemented_routes

MakeUser = Callable[..., str]
COOKIE = "__Host-gridora_session"


def login(c: TestClient, username: str = "alice", password: str = PASSWORD) -> Any:
    return c.post("/api/v1/auth/login", json={"username": username, "password": password})


def rows(sql: str, **params: Any) -> list[Any]:
    async def go(db: AsyncSession) -> list[Any]:
        return list((await db.execute(text(sql), params)).all())

    return run_db(go)


def run_sql(sql: str, **params: Any) -> None:
    async def go(db: AsyncSession) -> None:
        await db.execute(text(sql), params)

    run_db(go)


# ------------------------------------------------------------------ login ----
def test_login_returns_auth_result_and_cookie(client: TestClient, make_user: MakeUser) -> None:
    uid = make_user()
    r = login(client)
    assert r.status_code == 200
    result = AuthResult.model_validate(r.json()["data"])  # contract model validates the payload
    assert result.user.id == uid and result.user.username == "alice" and result.user.role == "user"
    assert len(result.csrf_token) >= 32
    assert r.json()["meta"]["request_id"] == r.headers["X-Request-ID"]

    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    low = cookie.lower()
    assert "httponly" in low and "secure" in low and "samesite=strict" in low and "path=/" in low
    assert "domain=" not in low  # required by the __Host- prefix


def test_session_token_is_stored_only_as_sha256(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(client)
    raw = client.cookies.get(COOKIE)
    assert raw
    stored = rows("select token_sha256 from sessions")
    assert [r[0] for r in stored] == [hashlib.sha256(raw.encode()).hexdigest()]
    assert raw not in str(rows("select * from sessions"))


def test_insecure_cookie_mode_is_explicit_dev_only(tmp_path: Path, make_user: MakeUser) -> None:
    make_user()
    app = create_app(fast_settings(tmp_path, env="dev", secure_cookies=False))
    with TestClient(app) as c:
        r = login(c)
    assert r.headers["set-cookie"].startswith("gridora_session=")
    assert "secure" not in r.headers["set-cookie"].lower()


def test_password_is_argon2id_and_never_stored_or_audited_in_clear(
    client: TestClient, make_user: MakeUser
) -> None:
    make_user()
    login(client)
    login(client, password="wrong password!!")
    (h,) = rows("select password_hash from users")[0]
    assert h.startswith("$argon2id$")
    dump = str(rows("select * from users")) + str(rows("select * from audit_log"))
    assert PASSWORD not in dump and "wrong password" not in dump


def test_wrong_password_and_unknown_user_look_identical(
    client: TestClient, make_user: MakeUser
) -> None:
    make_user()
    a = login(client, password="not the password")
    b = login(client, username="nobody")
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "unauthenticated"
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_username_is_case_insensitive(client: TestClient, make_user: MakeUser) -> None:
    make_user("Alice")
    assert login(client, username="aLiCe").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "a"},
        {"password": "x"},
        {"username": "a", "password": "x", "extra": 1},
        {"username": "a", "password": "x" * 2000},
        {"username": "u" * 65, "password": "x"},
    ],
)
def test_login_input_validation(client: TestClient, body: dict[str, Any]) -> None:
    r = client.post("/api/v1/auth/login", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"


def test_disabled_user_cannot_login_or_keep_session(
    client: TestClient, make_user: MakeUser
) -> None:
    make_user()
    assert login(client).status_code == 200
    run_sql("update users set is_active = false")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client).status_code == 401


# --------------------------------------------------------------- sessions ----
def test_me_requires_a_session(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_me_returns_same_csrf_token(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    tok = login(client).json()["data"]["csrf_token"]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["data"]["csrf_token"] == tok


def test_forged_cookie_is_rejected(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    client.cookies.set(COOKIE, "A" * 43)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rotates_session_no_fixation(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(client)
    old = client.cookies.get(COOKIE)
    login(client)
    new = client.cookies.get(COOKIE)
    assert old != new
    assert len(rows("select id from sessions")) == 1  # the old row was deleted, not kept
    client.cookies.set(COOKIE, old)  # type: ignore[arg-type]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_absolute_expiry(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(client)
    run_sql("update sessions set expires_at = now() - interval '1 second'")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert rows("select id from sessions") == []  # expired row is removed


def test_idle_expiry(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(client)
    run_sql("update sessions set last_seen_at = now() - interval '9 hours'")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_idle_window_slides(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(client)
    run_sql("update sessions set last_seen_at = now() - interval '2 hours'")
    assert client.get("/api/v1/auth/me").status_code == 200
    (age,) = rows("select extract(epoch from now() - last_seen_at) from sessions")[0]
    assert age < 60


# ------------------------------------------------------------------- CSRF ----
def test_logout_requires_csrf_token(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    login(client)
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200  # still logged in


def test_logout_with_token_ends_session(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    tok = login(client).json()["data"]["csrf_token"]
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": tok})
    assert r.status_code == 204
    assert rows("select id from sessions") == []
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_csrf_token_of_another_session_is_rejected(
    client: TestClient, make_user: MakeUser, app: FastAPI
) -> None:
    make_user("alice")
    make_user("bob")
    with TestClient(app, base_url="https://testserver") as other:
        other_tok = login(other, "bob").json()["data"]["csrf_token"]
    login(client, "alice")
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": other_tok})
    assert r.status_code == 403


def test_every_mutating_route_except_login_requires_a_session(app: FastAPI) -> None:
    """Future routes inherit this check: no cookie -> 401, so none can skip auth by accident."""
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        checked = 0
        for method, template in sorted(implemented_routes(app)):
            if (
                template == "/api/v1/auth/login"
                or method == "GET"
                and template != "/api/v1/auth/me"
            ):
                continue
            path = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", template)
            r = c.request(method, path)
            assert r.status_code == 401, f"{method} {template} is reachable without a session"
            checked += 1
        assert checked >= 2  # logout + me at least


# ----------------------------------------------------------- rate limiting ----
def test_rate_limit_after_repeated_failures(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    for _ in range(5):
        assert login(client, password="nope nope nope").status_code == 401
    r = login(client)  # even the correct password is refused while limited
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["Retry-After"]) <= 900


def test_rate_limit_is_per_user_and_resets_on_success(
    client: TestClient, make_user: MakeUser
) -> None:
    make_user("alice")
    make_user("bob")
    for _ in range(4):
        login(client, "alice", "nope nope nope")
    assert login(client, "alice").status_code == 200  # below the limit, then success resets
    for _ in range(4):
        login(client, "alice", "nope nope nope")
    assert login(client, "alice").status_code == 200  # counter had been reset
    for _ in range(5):
        login(client, "bob", "nope nope nope")
    assert login(client, "bob").status_code == 429
    assert login(client, "alice").status_code == 200  # alice unaffected by bob's lockout


def test_rate_limit_window_expires(client: TestClient, make_user: MakeUser) -> None:
    make_user()
    for _ in range(5):
        login(client, password="nope nope nope")
    run_sql("update login_attempts set window_start = now() - interval '1 hour'")
    assert login(client).status_code == 200


def test_login_attempt_keys_do_not_contain_raw_usernames(
    client: TestClient, make_user: MakeUser
) -> None:
    make_user()
    login(client, password="nope nope nope")
    keys = [r[0] for r in rows("select key from login_attempts")]
    assert keys and all("alice" not in k for k in keys)


# ------------------------------------------------------------------- audit ----
def test_audit_log_records_login_and_logout(client: TestClient, make_user: MakeUser) -> None:
    uid = make_user()
    login(client, password="nope nope nope")
    tok = login(client).json()["data"]["csrf_token"]
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": tok})
    got = rows("select action, outcome, actor_id::text, request_id from audit_log order by id")
    assert [(a, o) for a, o, _, _ in got] == [
        ("auth.login", "failure"),
        ("auth.login", "success"),
        ("auth.logout", "success"),
    ]
    assert got[0][2] is None and got[1][2] == uid
    assert all(r[3] for r in got)  # request ids are recorded


# ------------------------------------------------------------- bootstrap/CLI ----
def test_bootstrap_admin_created_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    s = fast_settings(
        tmp_path,
        bootstrap_admin_username="root",
        bootstrap_admin_password="a long bootstrap password",
    )
    with TestClient(create_app(s), base_url="https://testserver") as c:
        r = login(c, "root", "a long bootstrap password")
        assert r.status_code == 200 and r.json()["data"]["user"]["role"] == "admin"
    with TestClient(create_app(s)):
        pass  # second start must not create another user
    assert rows("select count(*) from users")[0][0] == 1
    assert "a long bootstrap password" not in caplog.text


def test_bootstrap_does_nothing_when_users_exist(tmp_path: Path, make_user: MakeUser) -> None:
    make_user()
    s = fast_settings(
        tmp_path,
        bootstrap_admin_username="root",
        bootstrap_admin_password="a long bootstrap password",
    )
    with TestClient(create_app(s)):
        pass
    assert rows("select username from users") == [("alice",)]


def test_cli_create_user_and_login(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, settings: Settings
) -> None:
    import io

    from gridora_api import cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.stdin", io.StringIO("a perfectly fine password\n"))
    assert cli.main(["create-user", "--username", "dana", "--admin", "--password-stdin"]) == 0
    r = login(client, "dana", "a perfectly fine password")
    assert r.status_code == 200 and r.json()["data"]["user"]["role"] == "admin"
    assert ("user.create", "success") in [
        (a, o) for a, o in rows("select action, outcome from audit_log")
    ]


def test_cli_rejects_short_password_and_duplicates(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    from gridora_api import cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["create-user", "--username", "eve", "--password-stdin"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("a perfectly fine password\n"))
    assert cli.main(["create-user", "--username", "eve", "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("a perfectly fine password\n"))
    assert cli.main(["create-user", "--username", "EVE", "--password-stdin"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_reset_password(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, settings: Settings, make_user: MakeUser
) -> None:
    import io

    from gridora_api import cli

    make_user()
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.stdin", io.StringIO("brand new password!\n"))
    assert cli.main(["reset-password", "--username", "alice", "--password-stdin"]) == 0
    assert login(client).status_code == 401
    assert login(client, password="brand new password!").status_code == 200
