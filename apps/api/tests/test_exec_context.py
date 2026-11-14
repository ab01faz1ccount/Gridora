from __future__ import annotations

from pathlib import Path

import pytest
from gridora_contracts.models import MAX_WINDOW_ROWS, NumValue, Range, StrValue, Window
from gridora_contracts.protocols import ExecContext

from gridora_api.composition.exec_context import MAX_PATCH_CELLS, EngineExecContext
from gridora_api.composition.stubs.executor_stub import StubTableStore
from gridora_api.core.errors import DomainError

from .stubkit import ctx_for, open_csv, rng


def test_satisfies_exec_context_protocol(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n1\n")
    ctx = ctx_for(eng, h)
    c: ExecContext = ctx
    assert c.user_id == "u" and c.workspace_id == "w"
    assert isinstance(c.table_store(), StubTableStore)


def test_read_range_is_typed_with_none_for_empty(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a,,c\n1,2,3\n")
    out = ctx_for(eng, h).read_range(rng(h, 0, 0, 1, 2))
    assert out[0][1] is None and out[0][0] is not None
    assert out[1][1] is not None and out[1][1].v == NumValue(n=2.0)  # typed, not stringified


def test_read_range_is_tiled_beyond_the_window_cap(tmp_path: Path) -> None:
    n = MAX_WINDOW_ROWS * 2 + 500
    body = "k\n" + "\n".join(str(i) for i in range(n))
    eng, h, _ = open_csv(tmp_path, body.encode())
    out = ctx_for(eng, h).read_range(rng(h, 1, 0, n, 0))
    assert len(out) == n
    assert out[0][0] is not None and out[0][0].v == NumValue(n=0.0)
    assert out[-1][0] is not None and out[-1][0].v == NumValue(n=float(n - 1))
    assert all(r[0] is not None for r in out)  # no tile boundary lost a row


def test_write_range_clears_uncovered_cells_in_one_delta(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a,b\n1,2\n3,4\n5,6\n")
    ctx = ctx_for(eng, h)
    d = ctx.write_range(rng(h, 1, 0, 3, 1), [[StrValue(s="x"), None]])  # shrinks 3x2 -> 1x1
    assert d.kind == "cell_patch" and len(d.after) == 6  # every cell of the range is covered
    flat = [c for row in ctx.read_range(rng(h, 1, 0, 3, 1)) for c in row]
    assert [c.v if c else None for c in flat] == [StrValue(s="x")] + [None] * 5
    eng.apply_delta(h, d, inverse=True)
    assert [c.v.n for c in (r for row in ctx.read_range(rng(h, 1, 0, 3, 1)) for r in row) if c] == [
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
    ]


def test_write_range_over_the_history_cap_is_a_typed_error(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n1\n")
    ctx = EngineExecContext(eng, h, user_id="u", workspace_id="w", store=StubTableStore())
    big = Range(sheet_id=h.sheet_id, r0=0, c0=0, r1=MAX_PATCH_CELLS, c1=1)  # 2*(cap+1) cells
    with pytest.raises(DomainError) as ei:
        ctx.write_range(big, [])
    assert ei.value.code == "operation_conflict"
    assert ei.value.details[0].code == "too_large_for_history"
    still = eng.get_cells(h, h.sheet_id, Window(row0=0, col0=0, rows=5, cols=5)).cells
    assert still[0].v == StrValue(s="a")  # the refused write changed nothing


def test_engine_is_not_exposed_to_dataops_through_the_context(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"a\n1\n")
    ctx = ctx_for(eng, h)
    public = {n for n in dir(ctx) if not n.startswith("_")}
    assert public == {"read_range", "write_range", "table_store", "user_id", "workspace_id"}
