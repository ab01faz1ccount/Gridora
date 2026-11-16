"""Errors as apps/api expects them (Review 4): the history-size limit is top-level `operation_conflict` with detail code
`too_large_for_history`; every dataops code maps to a valid top-level contract code."""
from __future__ import annotations

from pathlib import Path

import pytest
from fakes import RowFakeExecContext, num, txt
from gridora_contracts.models import ERROR_CODES, Operation, SheetRangeTarget

from gridora_dataops import DataOpsExecutor
from gridora_dataops.errors import ERROR_CODES as DATAOPS_CODES
from gridora_dataops.errors import ERROR_ENVELOPE, envelope


def test_every_dataops_code_has_an_envelope_with_a_valid_top_level_code() -> None:
    assert set(ERROR_ENVELOPE) == set(DATAOPS_CODES)
    for code in DATAOPS_CODES:
        top, detail = envelope(code)
        assert top in ERROR_CODES and detail == code


def test_the_history_limit_is_an_operation_conflict_with_that_detail_code() -> None:
    assert envelope("too_large_for_history") == ("operation_conflict", "too_large_for_history")


def test_the_cap_error_the_executor_produces_uses_that_code() -> None:
    ctx = RowFakeExecContext()
    ctx.fill([[txt("a"), txt("b")], [num(2), num(1)], [num(1), num(2)]])
    ex = DataOpsExecutor(max_patch_cells=4)
    res = ex.apply(Operation(type="sort", target=SheetRangeTarget(range=ctx.rng(0, 0, 2, 1)),
                             params={"keys": [{"column": "a"}]}), ctx)
    assert res.status == "error" and res.errors[0].code == "too_large_for_history" and ctx.writes == 0
    assert envelope(res.errors[0].code)[0] == "operation_conflict"


class ApiError(Exception):
    """Stands for the API's own DomainError, which dataops cannot import."""


class CappingContext(RowFakeExecContext):  # type: ignore[misc,valid-type]
    """Raises the API's error from write_range on the Nth call (the real ExecContext enforces the cap itself)."""

    fail_on = 1
    _raised = False

    def write_range(self, rng, rows):  # type: ignore[no-untyped-def]
        if self.writes + 1 == self.fail_on and not self._raised:
            self._raised = True
            raise ApiError("operation_conflict: too_large_for_history")
        return super().write_range(rng, rows)


def test_an_error_raised_by_the_context_propagates_from_apply_and_leaves_the_sheet_untouched() -> None:
    ctx = CappingContext()
    ctx.fill([[txt("a")], [num(2)], [num(1)]])
    before = ctx.snapshot()
    op = Operation(type="sort", target=SheetRangeTarget(range=ctx.rng(0, 0, 2, 0)), params={"keys": [{"column": "a"}]})
    with pytest.raises(ApiError):
        DataOpsExecutor().apply(op, ctx)
    assert ctx.snapshot() == before


@pytest.mark.parametrize("handoff", [True, False])
def test_in_a_pipeline_a_context_error_still_rolls_back_earlier_steps_then_propagates(handoff: bool, tmp_path: Path) -> None:
    from gridora_contracts.models import Pipeline, PipelineStep
    ctx = CappingContext()
    ctx.fail_on = 2
    ctx.fill([[txt("a"), txt("b")], [num(2), txt(" x ")], [num(1), txt("y")]])
    before = ctx.snapshot()
    p = Pipeline(name="p", input_kind="sheet_range", steps=[PipelineStep(type="clean_text", params={}),
                                                            PipelineStep(type="sort", params={"keys": [{"column": "a"}]})])
    with pytest.raises(ApiError):
        DataOpsExecutor(pipeline_handoff=handoff).run_pipeline(p, SheetRangeTarget(range=ctx.rng(0, 0, 2, 1)), ctx)
    assert ctx.snapshot() == before  # step 1 (clean_text trimmed " x ") was undone before the error went out
