"""One isolation case per /api/v1 route that takes an id. Each is run as ANOTHER user against
the owner's resource and must answer 404 (never 403/200) without changing anything."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Case = Callable[[Any, dict[str, str]], Any]

CSV = {"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}

ISOLATION_CASES: dict[tuple[str, str], Case] = {
    ("GET", "/api/v1/workspaces/{id}"): lambda c, ids: c.get(f"/api/v1/workspaces/{ids['ws']}"),
    ("PATCH", "/api/v1/workspaces/{id}"): lambda c, ids: c.patch(
        f"/api/v1/workspaces/{ids['ws']}", json={"name": "hijacked"}
    ),
    ("DELETE", "/api/v1/workspaces/{id}"): lambda c, ids: c.delete(
        f"/api/v1/workspaces/{ids['ws']}?confirm=true"
    ),
    ("GET", "/api/v1/workspaces/{id}/files"): lambda c, ids: c.get(
        f"/api/v1/workspaces/{ids['ws']}/files"
    ),
    ("POST", "/api/v1/workspaces/{id}/files"): lambda c, ids: c.post(
        f"/api/v1/workspaces/{ids['ws']}/files", files=CSV
    ),
    ("GET", "/api/v1/files/{id}/download"): lambda c, ids: c.get(
        f"/api/v1/files/{ids['file']}/download"
    ),
}
