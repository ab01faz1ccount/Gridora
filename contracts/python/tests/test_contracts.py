"""Contract smoke tests. Agents must keep these green; Agent 0 owns changes."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from gridora_contracts import (
    ApiErrorEnvelope, Cell, CellPatchDelta, ChartSpec, CompatibilityReport, CompatItem,
    CompatSummary, DataTableTarget, Operation, OperationExecutor, Range, SheetRangeTarget,
    Tool, Pipeline, PipelineStep, WorkbookEngine, ERROR_CODES, MAX_UPLOAD_BYTES,
)


def test_operation_discriminated_target_roundtrip():
    op = Operation(type="sort", target=SheetRangeTarget(range=Range(sheet_id="s", r0=0, c0=0, r1=9, c1=3)),
                   params={"column": 1, "order": "asc"})
    assert Operation.model_validate_json(op.model_dump_json()) == op
    op2 = Operation(type="dedupe", target=DataTableTarget(table_id="t"))
    assert op2.target.kind == "data_table"


def test_extra_fields_rejected():
    with pytest.raises(PydanticValidationError):
        Cell(r=0, c=0, bogus=1)


def test_negative_index_rejected():
    with pytest.raises(PydanticValidationError):
        Cell(r=-1, c=0)


def test_delta_union_by_kind():
    d = CellPatchDelta(sheet_id="s", before=[], after=[Cell(r=0, c=0)])
    assert d.kind == "cell_patch"


def test_compat_report_and_error_envelope():
    rep = CompatibilityReport(source="import", generated_at=datetime.now(timezone.utc),
                              items=[CompatItem(code="xlsx.pivot_table", status="unsupported",
                                                preserved=True, editable=False, message="x")],
                              summary=CompatSummary(unsupported=1))
    assert rep.items[0].preserved
    env = ApiErrorEnvelope(error={"code": "not_found", "message": "m", "request_id": "r"})
    assert env.error.code in ERROR_CODES


def test_tool_wraps_pipeline_and_chart_spec():
    Tool(name="clean", pipeline=Pipeline(name="p", input_kind="data_table",
                                         steps=[PipelineStep(type="trim")]))
    ChartSpec(document_id="d", type="bar", source=DataTableTarget(table_id="t"),
              series=[{"value_col": "amount", "category_col": "month", "aggregate": "sum"}])


def test_protocols_are_importable_and_runtime_checkable():
    assert hasattr(WorkbookEngine, "import_xlsx") and hasattr(OperationExecutor, "apply")


def test_upload_limit_is_100mb():
    assert MAX_UPLOAD_BYTES == 100 * 1024 * 1024
