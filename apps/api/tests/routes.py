"""Enumerate the app's /api/v1 routes from its OpenAPI document.

(Walking app.routes is not reliable: newer FastAPI wraps included routers lazily, which made a
first version of these tests see zero routes. OpenAPI is also what clients consume.)
"""

from __future__ import annotations

from fastapi import FastAPI

HTTP = {"get", "post", "put", "patch", "delete"}


def implemented_routes(app: FastAPI, prefix: str = "/api/v1") -> set[tuple[str, str]]:
    app.openapi_schema = None  # routes may have been added after the first call
    paths = app.openapi()["paths"]
    return {
        (m.upper(), p) for p, ops in paths.items() if p.startswith(prefix) for m in ops if m in HTTP
    }
