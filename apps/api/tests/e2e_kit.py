"""Shared helpers for the end-to-end API tests."""

from __future__ import annotations

from typing import Any

from .conftest import Session
from .helpers import import_csv

CSV = "نام,تعداد,شهر\nعلی,3,تهران\nرضا,4.5,شیراز\n".encode()


def NUM(n: float) -> dict[str, Any]:  # noqa: N802
    return {"k": "num", "n": n}


def STR(s: str) -> dict[str, Any]:  # noqa: N802
    return {"k": "str", "s": s}


class Doc:
    """Small helper around one imported workbook."""

    def __init__(self, s: Session, kind: str, data: bytes = CSV, name: str = "t.csv") -> None:
        self.s, self.kind = s, kind
        ws = s.post("/api/v1/workspaces", json={"name": "w"}).json()["data"]["id"]
        self.ids = import_csv(s, ws, name, data)
        self.wb, self.sheet = self.ids["wb"], self.ids["sheet"]

    def cells(self, rows: int = 20, cols: int = 10) -> dict[tuple[int, int], Any]:
        r = self.s.get(
            f"/api/v1/workbooks/{self.wb}/sheets/{self.sheet}/cells?r0=0&c0=0&rows={rows}&cols={cols}"
        )
        assert r.status_code == 200, r.text
        return {(c["r"], c["c"]): c.get("v") for c in r.json()["data"]["cells"]}

    def edit(self, edits: list[dict[str, Any]], base_seq: int = 0) -> Any:
        return self.s.patch(
            f"/api/v1/workbooks/{self.wb}/sheets/{self.sheet}/cells",
            json={"base_seq": base_seq, "edits": edits},
        )

    def history(self, q: str = "") -> Any:
        return self.s.get(f"/api/v1/documents/{self.wb}/history{q}")

    def undo(self, q: str = "") -> Any:
        return self.s.post(f"/api/v1/documents/{self.wb}/undo{q}")

    def redo(self, q: str = "") -> Any:
        return self.s.post(f"/api/v1/documents/{self.wb}/redo{q}")


def set_cell(r: int, c: int, value: dict[str, Any] | None) -> dict[str, Any]:
    return {"r": r, "c": c, **({"value": value} if value else {})}
