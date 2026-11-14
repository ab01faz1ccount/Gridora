"""Isolation harness (PLAN 2.4): every route with an id path parameter needs an isolation case.

PR 2 has no such route yet, so the registry is empty and the real check passes trivially. The
self-test proves the harness would FAIL on an uncovered route, so it cannot silently rot.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routes import implemented_routes

# (METHOD, path template) -> reason/test reference. Filled in by the PRs that add owned resources.
ISOLATION_CASES: dict[tuple[str, str], str] = {}


def uncovered_routes(app: FastAPI, cases: dict[tuple[str, str], str]) -> list[tuple[str, str]]:
    return sorted((m, p) for m, p in implemented_routes(app) if "{" in p and (m, p) not in cases)


def test_all_id_routes_have_an_isolation_case(app: FastAPI) -> None:
    assert uncovered_routes(app, ISOLATION_CASES) == []


def test_harness_detects_an_uncovered_route(app: FastAPI) -> None:
    @app.get("/api/v1/widgets/{widget_id}")
    async def widget(widget_id: str) -> None: ...

    assert uncovered_routes(app, ISOLATION_CASES) == [("GET", "/api/v1/widgets/{widget_id}")]
    assert uncovered_routes(app, {("GET", "/api/v1/widgets/{widget_id}"): "x"}) == []
