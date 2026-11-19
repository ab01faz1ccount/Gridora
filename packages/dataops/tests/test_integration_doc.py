"""INTEGRATION.md is executable documentation: the python block marked `integration-test` is run against the in-memory double."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fakes import ColumnarFakeExecContext, RowFakeExecContext, num, txt
from gridora_contracts.models import ERROR_CODES

DOC = (Path(__file__).resolve().parents[1] / "INTEGRATION.md").read_text(encoding="utf-8")


def snippet() -> str:
    m = re.search(r"```python integration-test\n(.*?)```", DOC, re.DOTALL)
    assert m, "INTEGRATION.md lost its runnable block"
    return m.group(1)


@pytest.mark.parametrize("cls", [RowFakeExecContext, ColumnarFakeExecContext], ids=["row", "columnar"])
def test_the_documented_call_sequence_runs(tmp_path: Path, cls: type) -> None:
    probe = cls()
    probe.fill([[txt("نام"), txt("شهر"), txt("تعداد")], [txt("علی"), txt("تهران"), num(3)], [txt("سارا"), txt("کرج"), num(1)],
                [txt("علی"), txt("تهران"), num(3)]])
    ns: dict[str, object] = {
        "DATA_ROOT": tmp_path, "RANGE": probe.rng(0, 0, 3, 2), "RANGE_AFTER": probe.rng(0, 0, 2, 2),
        "make_ctx": lambda store: _bind(cls, store, probe),
    }
    exec(compile(snippet(), "INTEGRATION.md", "exec"), ns)  # noqa: S102 - our own documentation
    assert ns["hits"][0].type == "remove_duplicates"  # type: ignore[index,attr-defined]
    panel = ns["panel"]
    assert panel["effect"]["rows_removed"] == 1 and panel["lines"] == ["۱ ردیف حذف می‌شود"]  # type: ignore[index]
    assert panel["apply_label"] == "حذف ۱ ردیف" and panel["confirm"] is True  # type: ignore[index]
    assert ns["toast"] == "۱ ردیف حذف شد"
    assert ns["table"].version == 1 and ns["restored"].version == 1 and len(ns["page"]) == 2  # type: ignore[attr-defined]
    assert str(tmp_path / "users" / "u1" / "tables") in str(ns["path_for"]("u1", "x", 1))  # type: ignore[operator]


def _bind(cls: type, store: object, probe: object) -> object:
    ctx = cls(store=store)
    ctx.grid = dict(probe.grid)  # type: ignore[attr-defined]
    return ctx


def test_every_error_code_named_in_the_error_table_is_real_and_complete() -> None:
    from gridora_dataops.errors import ERROR_CODES as MINE
    from gridora_dataops.errors import ERROR_ENVELOPE
    table = DOC.split("## 5. Errors")[1].split("## 6.")[0]
    named = set(re.findall(r"`([a-z_]+)`", table))
    assert set(MINE) <= named, f"missing in the doc: {sorted(set(MINE) - named)}"
    for top in {t for t, _ in ERROR_ENVELOPE.values()}:
        assert top in ERROR_CODES and f"`{top}`" in table


def test_the_documented_config_keys_exist() -> None:
    from gridora_dataops import create_executor
    ex = create_executor({"max_patch_cells": 7, "columnar_sheets": False, "pipeline_handoff": False, "handoff_max_bytes": 5})
    assert (ex.max_patch_cells, ex.columnar, ex.pipeline_handoff, ex.handoff_max_bytes) == (7, False, False, 5)
    for key in ("max_patch_cells", "columnar_sheets", "pipeline_handoff", "handoff_max_bytes"):
        assert f"`{key}`" in DOC
    assert "536870912" in DOC  # the documented default equals the code's
    from gridora_dataops.executor import DEFAULT_HANDOFF_MAX_BYTES
    assert DEFAULT_HANDOFF_MAX_BYTES == 536870912
