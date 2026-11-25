"""One isolation case per /api/v1 route that takes an id. Each is run as ANOTHER user against
the owner's resource and must answer 404 (never 403/200) without changing anything."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Case = Callable[[Any, dict[str, str]], Any]

CSV = {"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}

def _TABLE_SORT(ids: dict[str, str]) -> dict[str, object]:  # noqa: N802
    return {
        "type": "sort",
        "target": {"kind": "data_table", "table_id": ids["table"]},
        "params": {"keys": [{"column": "a"}]},
    }


TOOL: dict[str, object] = {
    "name": "sort by a column",
    "pipeline": {
        "name": "p",
        "input_kind": "sheet_range",
        "steps": [
            {
                "type": "sort",
                "params": {"keys": [{"column": {"$input": "col"}, "direction": "asc"}]},
            }
        ],
    },
    "inputs": [{"name": "col", "kind": "column", "label": "column"}],
}


def _CHART(ids: dict[str, str]) -> dict[str, object]:  # noqa: N802
    return {
        "document_id": ids["wb"],
        "type": "bar",
        "source": {
            "kind": "sheet_range",
            "range": {"sheet_id": ids["sheet"], "r0": 0, "c0": 0, "r1": 2, "c1": 2},
        },
        "series": [{"value_col": "تعداد", "category_col": "شهر"}],
    }


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
    ("GET", "/api/v1/jobs/{id}"): lambda c, ids: c.get(f"/api/v1/jobs/{ids['job']}"),
    ("POST", "/api/v1/files/{id}/open"): lambda c, ids: c.post(f"/api/v1/files/{ids['file']}/open"),
    ("GET", "/api/v1/workbooks/{id}"): lambda c, ids: c.get(f"/api/v1/workbooks/{ids['wb']}"),
    ("GET", "/api/v1/workbooks/{id}/compatibility"): lambda c, ids: c.get(
        f"/api/v1/workbooks/{ids['wb']}/compatibility"
    ),
    ("GET", "/api/v1/workbooks/{id}/sheets/{sheet_id}/cells"): lambda c, ids: c.get(
        f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/cells?r0=0&c0=0&rows=5&cols=5"
    ),
    ("PATCH", "/api/v1/workbooks/{id}/sheets/{sheet_id}/cells"): lambda c, ids: c.patch(
        f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/cells",
        json={"base_seq": 0, "edits": [{"r": 0, "c": 0, "value": {"k": "num", "n": 1}}]},
    ),
    ("GET", "/api/v1/workbooks/{id}/sheets/{sheet_id}/date-columns"): lambda c, ids: c.get(
        f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/date-columns"
    ),
    ("GET", "/api/v1/workbooks/{id}/sheets/{sheet_id}/find"): lambda c, ids: c.get(
        f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/find?q=a"
    ),
    ("POST", "/api/v1/workbooks/{id}/sheets/{sheet_id}/fill"): lambda c, ids: c.post(
        f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/fill",
        json={
            "base_seq": 0,
            "source": {"sheet_id": ids["sheet"], "r0": 0, "c0": 0, "r1": 0, "c1": 0},
            "target": {"sheet_id": ids["sheet"], "r0": 1, "c0": 0, "r1": 2, "c1": 0},
        },
    ),
    ("PUT", "/api/v1/workbooks/{id}/sheets/{sheet_id}/frozen"): lambda c, ids: c.put(
        f"/api/v1/workbooks/{ids['wb']}/sheets/{ids['sheet']}/frozen", json={"rows": 1, "cols": 0}
    ),
    ("PUT", "/api/v1/workbooks/{id}/calendar"): lambda c, ids: c.put(
        f"/api/v1/workbooks/{ids['wb']}/calendar", json={"calendar": "hijri"}
    ),
    ("POST", "/api/v1/workbooks/{id}/save"): lambda c, ids: c.post(
        f"/api/v1/workbooks/{ids['wb']}/save"
    ),
    ("POST", "/api/v1/workbooks/{id}/export"): lambda c, ids: c.post(
        f"/api/v1/workbooks/{ids['wb']}/export", json={"format": "xlsx"}
    ),
    ("GET", "/api/v1/jobs/{id}/compatibility"): lambda c, ids: c.get(
        f"/api/v1/jobs/{ids['job']}/compatibility"
    ),
    ("GET", "/api/v1/workspaces/{id}/tables"): lambda c, ids: c.get(
        f"/api/v1/workspaces/{ids['ws']}/tables"
    ),
    ("POST", "/api/v1/workspaces/{id}/tables"): lambda c, ids: c.post(
        f"/api/v1/workspaces/{ids['ws']}/tables",
        json={"name": "t", "columns": [{"name": "a", "dtype": "int64"}], "rows": [[1]]},
    ),
    ("POST", "/api/v1/tables/from-range"): lambda c, ids: c.post(
        "/api/v1/tables/from-range",
        json={
            "workbook_id": ids["wb"],
            "range": {"sheet_id": ids["sheet"], "r0": 0, "c0": 0, "r1": 1, "c1": 1},
        },
    ),
    ("GET", "/api/v1/tables/{id}"): lambda c, ids: c.get(f"/api/v1/tables/{ids['table']}"),
    ("GET", "/api/v1/tables/{id}/rows"): lambda c, ids: c.get(
        f"/api/v1/tables/{ids['table']}/rows"
    ),
    ("POST", "/api/v1/tables/{id}/to-sheet"): lambda c, ids: c.post(
        f"/api/v1/tables/{ids['table']}/to-sheet",
        json={"workbook_id": ids["wb"], "sheet_id": ids["sheet"]},
    ),
    ("GET", "/api/v1/documents/{id}/charts"): lambda c, ids: c.get(
        f"/api/v1/documents/{ids['wb']}/charts"
    ),
    ("POST", "/api/v1/documents/{id}/charts"): lambda c, ids: c.post(
        f"/api/v1/documents/{ids['wb']}/charts", json=_CHART(ids)
    ),
    ("PUT", "/api/v1/charts/{id}"): lambda c, ids: c.put(
        f"/api/v1/charts/{ids['chart']}", json=_CHART(ids)
    ),
    ("DELETE", "/api/v1/charts/{id}"): lambda c, ids: c.delete(f"/api/v1/charts/{ids['chart']}"),
    ("GET", "/api/v1/charts/{id}/data"): lambda c, ids: c.get(
        f"/api/v1/charts/{ids['chart']}/data"
    ),
    ("GET", "/api/v1/tools/{id}"): lambda c, ids: c.get(f"/api/v1/tools/{ids['tool']}"),
    ("PUT", "/api/v1/tools/{id}"): lambda c, ids: c.put(
        f"/api/v1/tools/{ids['tool']}", json=TOOL
    ),
    ("DELETE", "/api/v1/tools/{id}"): lambda c, ids: c.delete(f"/api/v1/tools/{ids['tool']}"),
    ("POST", "/api/v1/tools/{id}/run"): lambda c, ids: c.post(
        f"/api/v1/tools/{ids['tool']}/run",
        json={
            "workbook_id": ids["wb"],
            "base_seq": 0,
            "target": {
                "kind": "sheet_range",
                "range": {"sheet_id": ids["sheet"], "r0": 0, "c0": 0, "r1": 1, "c1": 1},
            },
        },
    ),
    ("POST", "/api/v1/tables/{id}/operations/preview"): lambda c, ids: c.post(
        f"/api/v1/tables/{ids['table']}/operations/preview", json=_TABLE_SORT(ids)
    ),
    ("POST", "/api/v1/tables/{id}/operations"): lambda c, ids: c.post(
        f"/api/v1/tables/{ids['table']}/operations",
        json={"operation": _TABLE_SORT(ids), "base_seq": 0},
    ),
    ("POST", "/api/v1/tables/{id}/undo"): lambda c, ids: c.post(
        f"/api/v1/tables/{ids['table']}/undo"
    ),
    ("POST", "/api/v1/tables/{id}/redo"): lambda c, ids: c.post(
        f"/api/v1/tables/{ids['table']}/redo"
    ),
    ("GET", "/api/v1/tables/{id}/history"): lambda c, ids: c.get(
        f"/api/v1/tables/{ids['table']}/history"
    ),
    ("POST", "/api/v1/tables/{id}/export"): lambda c, ids: c.post(
        f"/api/v1/tables/{ids['table']}/export", json={"format": "csv"}
    ),
    ("GET", "/api/v1/documents/{id}/history"): lambda c, ids: c.get(
        f"/api/v1/documents/{ids['wb']}/history"
    ),
    ("POST", "/api/v1/documents/{id}/undo"): lambda c, ids: c.post(
        f"/api/v1/documents/{ids['wb']}/undo"
    ),
    ("POST", "/api/v1/documents/{id}/redo"): lambda c, ids: c.post(
        f"/api/v1/documents/{ids['wb']}/redo"
    ),
    ("POST", "/api/v1/documents/{id}/operations/preview"): lambda c, ids: c.post(
        f"/api/v1/documents/{ids['wb']}/operations/preview",
        json={
            "type": "sort",
            "params": {"columns": [{"column": 0}]},
            "target": {
                "kind": "sheet_range",
                "range": {"sheet_id": ids["sheet"], "r0": 0, "c0": 0, "r1": 1, "c1": 1},
            },
        },
    ),
    ("POST", "/api/v1/documents/{id}/operations"): lambda c, ids: c.post(
        f"/api/v1/documents/{ids['wb']}/operations",
        json={
            "base_seq": 0,
            "operation": {
                "type": "sort",
                "params": {"columns": [{"column": 0}]},
                "target": {
                    "kind": "sheet_range",
                    "range": {"sheet_id": ids["sheet"], "r0": 0, "c0": 0, "r1": 1, "c1": 1},
                },
            },
        },
    ),
}
