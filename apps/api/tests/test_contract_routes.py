from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from .contract_routes import PREFIX, contract_routes


def _implemented(app: FastAPI) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith(PREFIX):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                out.add((m, r.path))
    return out


def test_contract_table_is_parsed() -> None:
    routes = contract_routes()
    # Guards against the regex silently matching nothing if the doc layout changes.
    assert len(routes) >= 40
    assert ("POST", "/api/v1/auth/login") in routes
    assert ("PATCH", "/api/v1/workbooks/{id}/sheets/{sheet_id}/cells") in routes
    assert ("GET", "/api/v1/operations/i18n") in routes


def test_implemented_routes_are_a_subset_of_the_contract(app: FastAPI) -> None:
    extra = _implemented(app) - contract_routes()
    assert not extra, f"routes not in docs/API_CONTRACTS.md: {sorted(extra)}"


def test_report_unimplemented(app: FastAPI, capsys: object) -> None:
    missing = contract_routes() - _implemented(app)
    # Informational: shows progress without pretending anything is done.
    print(f"\ncontract routes implemented: {len(contract_routes()) - len(missing)}"
          f"/{len(contract_routes())}")
