"""Helpers shared by the stub/composition tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gridora_contracts.models import Operation, Range, SheetRangeTarget, Workbook

from gridora_api.composition.exec_context import EngineExecContext
from gridora_api.composition.stubs.engine_stub import StubEngine, StubHandle
from gridora_api.composition.stubs.executor_stub import StubExecutor, StubTableStore


@dataclass
class Opts:
    delimiter: str | None = None
    encoding: str | None = None
    has_header: bool = True
    infer_types: bool = True


def open_csv(
    tmp_path: Path, content: bytes, file_id: str | None = None, **kw: object
) -> tuple[StubEngine, StubHandle, Workbook]:
    p = tmp_path / "in.csv"
    p.write_bytes(content)
    eng = StubEngine()
    h, wb = eng.import_csv(p, Opts(**kw), file_id=file_id)  # type: ignore[arg-type]
    assert isinstance(h, StubHandle)
    return eng, h, wb


def ctx_for(eng: StubEngine, h: StubHandle) -> EngineExecContext:
    return EngineExecContext(eng, h, user_id="u", workspace_id="w", store=StubTableStore())


def rng(h: StubHandle, r0: int, c0: int, r1: int, c1: int) -> Range:
    return Range(sheet_id=h.sheet_id, r0=r0, c0=c0, r1=r1, c1=c1)


def op(h: StubHandle, type_: str, r: Range, **params: object) -> Operation:
    return Operation(type=type_, target=SheetRangeTarget(range=r), params=dict(params))


EXEC = StubExecutor()
