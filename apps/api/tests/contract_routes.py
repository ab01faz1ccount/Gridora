"""Route table of the contract, parsed from docs/API_CONTRACTS.md (single source of truth).

Rows look like:  | GET/POST | `/workspaces` | ... |   -> (GET, /api/v1/workspaces), (POST, ...)
Query strings in the doc (`?r0&c0`) are dropped. v0.2 additions that are only described in
prose (section 11a) are listed explicitly in EXTRA_ROUTES.
"""

from __future__ import annotations

import re
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "API_CONTRACTS.md"
PREFIX = "/api/v1"

# Routes described in prose rather than in a table row:
#   section 4: GET /jobs/{id};  section 11a: GET /operations/i18n?locale=fa
EXTRA_ROUTES: set[tuple[str, str]] = {
    ("GET", PREFIX + "/operations/i18n"),
    ("GET", PREFIX + "/jobs/{id}"),
}

_ROW = re.compile(r"^\|\s*([A-Z]+(?:/[A-Z]+)*)\s*\|\s*`(/[^`]*)`")


def contract_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        path = m.group(2).split("?")[0]
        for method in m.group(1).split("/"):
            routes.add((method, PREFIX + path))
    return routes | EXTRA_ROUTES
