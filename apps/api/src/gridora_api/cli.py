"""Operator CLI: python -m gridora_api.cli <command>.

User creation is CLI-only in v1 (Agent 0 decision): there are no HTTP admin endpoints.
Passwords are read from a prompt or stdin, never from argv (they would show up in `ps`).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from .config import Settings, get_settings
from .db.models import User
from .db.session import make_engine, make_sessionmaker
from .services import audit
from .services.auth import create_user, normalize_username
from .services.passwords import Hasher


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat: "):
        raise SystemExit("passwords do not match")
    return first


async def _create_user(settings: Settings, username: str, password: str, admin: bool) -> None:
    engine = make_engine(settings)
    try:
        async with make_sessionmaker(engine)() as db:
            user = await create_user(
                db,
                Hasher(settings),
                username=username,
                password=password,
                role="admin" if admin else "user",
            )
            audit.record(
                db,
                action="user.create",
                outcome="success",
                target_kind="user",
                target_id=str(user.id),
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _reset_password(settings: Settings, username: str, password: str) -> None:
    from .services.auth import MAX_PASSWORD_LEN, MIN_PASSWORD_LEN

    if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        raise SystemExit(f"password must be {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} characters")
    engine = make_engine(settings)
    try:
        async with make_sessionmaker(engine)() as db:
            user = (
                await db.execute(select(User).where(User.username == normalize_username(username)))
            ).scalar_one_or_none()
            if user is None:
                raise SystemExit("no such user")
            user.password_hash = await Hasher(settings).hash(password)
            audit.record(
                db,
                action="user.reset_password",
                outcome="success",
                target_kind="user",
                target_id=str(user.id),
            )
            await db.commit()
    finally:
        await engine.dispose()


def _check_config(settings: Settings) -> None:
    url = settings.database_url
    if "@" in url and "://" in url:  # mask credentials
        scheme, rest = url.split("://", 1)
        url = f"{scheme}://***@{rest.split('@', 1)[1]}"
    print(f"env={settings.env} engine={settings.engine} dataops={settings.dataops}")
    print(f"database_url={url}")
    print(f"data_root={settings.data_root} secure_cookies={settings.secure_cookies}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gridora_api.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--username", required=True)
    c.add_argument("--admin", action="store_true")
    c.add_argument("--password-stdin", action="store_true")
    r = sub.add_parser("reset-password")
    r.add_argument("--username", required=True)
    r.add_argument("--password-stdin", action="store_true")
    sub.add_parser("check-config")
    args = p.parse_args(argv)
    settings = get_settings()
    if args.cmd == "check-config":
        _check_config(settings)
        return 0
    password = _read_password(args.password_stdin)
    try:
        if args.cmd == "create-user":
            asyncio.run(_create_user(settings, args.username, password, args.admin))
            print("user created")
        else:
            asyncio.run(_reset_password(settings, args.username, password))
            print("password updated")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
