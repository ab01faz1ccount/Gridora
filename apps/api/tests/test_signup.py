"""Self-service sign-up, password change and per-account quotas."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from gridora_contracts.models import AuthResult

from gridora_api.main import create_app

from .conftest import PASSWORD, fast_settings
from .test_auth import rows

GOOD = "correct horse battery"


def register(c: TestClient, username: str = "newuser", password: str = GOOD) -> Any:
    return c.post("/api/v1/auth/register", json={"username": username, "password": password})


def reasons(r: Any) -> list[str]:
    return [d["code"] for d in r.json()["error"]["details"]]


def test_register_creates_a_plain_user_with_a_session(client: TestClient) -> None:
    r = register(client)
    assert r.status_code == 201
    result = AuthResult.model_validate(r.json()["data"])
    assert result.user.username == "newuser" and result.user.role == "user"
    assert (
        "__Host-gridora_session" in r.headers["set-cookie"]
        and "HttpOnly" in r.headers["set-cookie"]
    )
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["data"]["user"]["username"] == "newuser"
    assert rows("select role from users where username='newuser'") == [("user",)]
    assert rows("select outcome from audit_log where action='auth.register'") == [("success",)]
    # the password is stored only as an argon2id hash
    assert rows("select password_hash from users")[0][0].startswith("$argon2id$")


def test_the_new_user_can_log_in_again_and_extra_fields_are_refused(client: TestClient) -> None:
    assert register(client).status_code == 201
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"username": "newuser", "password": GOOD})
    assert r.status_code == 200
    r = client.post(
        "/api/v1/auth/register", json={"username": "x_user", "password": GOOD, "role": "admin"}
    )
    assert r.status_code == 400  # a client can never ask for a role


def test_weak_or_bad_input_is_refused_with_reasons(client: TestClient) -> None:
    assert "auth.password_too_short" in reasons(register(client, password="short"))
    assert "auth.password_common" in reasons(register(client, password="password123"))
    assert "auth.password_common" in reasons(
        register(client, username="somebodyelse", password="SomebodyElse")
    )
    assert "auth.password_common" in reasons(register(client, password="aaaaaaaaaaaa"))
    assert "auth.username_invalid" in reasons(register(client, username="a b"))
    assert "auth.username_invalid" in reasons(register(client, username="ab"))
    assert rows("select count(*) from users")[0][0] == 0


def test_taken_and_reserved_names(client: TestClient, make_user: Callable[..., str]) -> None:
    make_user("alice")
    r = register(client, username="ALICE")  # names are case-insensitive
    assert r.status_code == 409 and reasons(r) == ["auth.username_taken"]
    assert reasons(register(client, username="admin")) == ["auth.username_taken"]
    assert reasons(register(client, username="Root")) == ["auth.username_taken"]


def test_persian_usernames_work(client: TestClient) -> None:
    assert register(client, username="کاربر_نمونه").status_code == 201


def test_registration_is_rate_limited_per_ip(tmp_path: Path, make_user: Callable[..., str]) -> None:
    s = fast_settings(tmp_path, register_max_per_ip=3)
    with TestClient(create_app(s), base_url="https://testserver") as c:
        for i in range(3):
            assert register(c, username=f"user{i}x").status_code == 201
            c.cookies.clear()
        r = register(c, username="user9x")
        assert r.status_code == 429 and "Retry-After" in r.headers
    assert rows("select count(*) from users")[0][0] == 3


def test_registration_can_be_turned_off(tmp_path: Path) -> None:
    s = fast_settings(tmp_path, registration_enabled=False)
    with TestClient(create_app(s), base_url="https://testserver") as c:
        assert c.get("/api/v1/auth/config").json()["data"]["registration_enabled"] is False
        r = register(c)
        assert r.status_code == 403 and reasons(r) == ["auth.registration_disabled"]
    assert rows("select count(*) from users")[0][0] == 0


def test_config_is_public(client: TestClient) -> None:
    d = client.get("/api/v1/auth/config").json()["data"]
    assert d == {"registration_enabled": True, "password_min_length": 10}


def test_user_limit(tmp_path: Path) -> None:
    s = fast_settings(tmp_path, max_users=2)
    with TestClient(create_app(s), base_url="https://testserver") as c:
        assert register(c, username="first_user").status_code == 201
        c.cookies.clear()
        assert register(c, username="second_user").status_code == 201
        c.cookies.clear()
        r = register(c, username="third_user")
        assert r.status_code == 409 and reasons(r) == ["auth.registration_full"]


def test_two_new_users_cannot_see_each_others_work(make_client: Callable[[], TestClient]) -> None:
    a, b = make_client(), make_client()
    ra = register(a, "user_a")
    rb = register(b, "user_b")
    a.headers["X-CSRF-Token"] = ra.json()["data"]["csrf_token"]
    b.headers["X-CSRF-Token"] = rb.json()["data"]["csrf_token"]
    ws = a.post("/api/v1/workspaces", json={"name": "private"})
    assert ws.status_code == 201
    wid = ws.json()["data"]["id"]
    assert b.get("/api/v1/workspaces").json()["data"] == []
    assert b.get(f"/api/v1/workspaces/{wid}/files").status_code == 404
    assert b.delete(f"/api/v1/workspaces/{wid}").status_code == 404


# ------------------------------------------------------------ password change ----
def test_change_password_ends_other_sessions_but_keeps_this_one(
    make_client: Callable[[], TestClient],
) -> None:
    a, other = make_client(), make_client()
    r = register(a, "pw_user")
    a.headers["X-CSRF-Token"] = r.json()["data"]["csrf_token"]
    assert (
        other.post("/api/v1/auth/login", json={"username": "pw_user", "password": GOOD}).status_code
        == 200
    )
    new = "a different long phrase"
    r = a.post("/api/v1/auth/password", json={"current_password": GOOD, "new_password": new})
    assert r.status_code == 204
    assert a.get("/api/v1/auth/me").status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 401  # the other device is signed out
    a.cookies.clear()
    assert (
        a.post("/api/v1/auth/login", json={"username": "pw_user", "password": GOOD}).status_code
        == 401
    )
    assert (
        a.post("/api/v1/auth/login", json={"username": "pw_user", "password": new}).status_code
        == 200
    )


def test_change_password_checks_current_policy_and_csrf(
    make_client: Callable[[], TestClient],
) -> None:
    a = make_client()
    r = register(a, "pw_user")
    csrf = r.json()["data"]["csrf_token"]
    body = {"current_password": GOOD, "new_password": "a different long phrase"}
    assert a.post("/api/v1/auth/password", json=body).status_code == 403  # no CSRF token
    a.headers["X-CSRF-Token"] = csrf
    bad = a.post("/api/v1/auth/password", json={**body, "current_password": "not my password"})
    assert bad.status_code == 401
    weak = a.post("/api/v1/auth/password", json={**body, "new_password": "short"})
    assert weak.status_code == 400 and "auth.password_too_short" in reasons(weak)
    same = a.post("/api/v1/auth/password", json={"current_password": GOOD, "new_password": GOOD})
    assert "auth.password_unchanged" in reasons(same)


def test_change_password_needs_a_session(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/password", json={"current_password": GOOD, "new_password": PASSWORD}
    )
    assert r.status_code == 401


# ------------------------------------------------------------------- quotas ----
def test_workspace_quota_applies_to_users_not_admins(
    tmp_path: Path, make_user: Callable[..., str]
) -> None:
    s = fast_settings(tmp_path, max_workspaces_per_user=2)
    make_user("boss", role="admin")
    with TestClient(create_app(s), base_url="https://testserver") as c:
        r = register(c, "limited_user")
        c.headers["X-CSRF-Token"] = r.json()["data"]["csrf_token"]
        for n in ("a", "b"):
            assert c.post("/api/v1/workspaces", json={"name": n}).status_code == 201
        r = c.post("/api/v1/workspaces", json={"name": "c"})
        assert r.status_code == 409 and reasons(r) == ["quota.workspaces"]
        c.cookies.clear()
        r = c.post("/api/v1/auth/login", json={"username": "boss", "password": PASSWORD})
        c.headers["X-CSRF-Token"] = r.json()["data"]["csrf_token"]
        for n in ("a", "b", "c"):
            assert c.post("/api/v1/workspaces", json={"name": n}).status_code == 201


def test_storage_quota_refuses_the_upload_and_leaves_nothing(tmp_path: Path) -> None:
    s = fast_settings(tmp_path, user_storage_bytes=100)
    with TestClient(create_app(s), base_url="https://testserver") as c:
        r = register(c, "small_quota")
        c.headers["X-CSRF-Token"] = r.json()["data"]["csrf_token"]
        wid = c.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
        up = c.post(
            f"/api/v1/workspaces/{wid}/files",
            files={"file": ("big.csv", b"a,b\n" + b"1,2\n" * 100)},
        )
        assert up.status_code == 409 and reasons(up) == ["quota.storage"]
        assert rows("select count(*) from files")[0][0] == 0
        ok = c.post(f"/api/v1/workspaces/{wid}/files", files={"file": ("ok.csv", b"a,b\n1,2\n")})
        assert ok.status_code == 201
