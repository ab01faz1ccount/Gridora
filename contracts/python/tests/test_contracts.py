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


# ---- contract v0.2 additions ----
from gridora_contracts import (  # noqa: E402
    AuthResult, CellEditRequest, CellsChangedResult, ExecContext, FormattingEngine, HistoryEntry,
    MAX_WINDOW_COLS, MAX_WINDOW_ROWS, SheetLayout, StructureEngine, StyleInfo, TableStore,
    TableVersionDelta, Window,
)


def test_window_limits_are_1000x100():
    assert (MAX_WINDOW_ROWS, MAX_WINDOW_COLS) == (1000, 100)
    Window(row0=0, col0=0, rows=1000, cols=100)
    with pytest.raises(PydanticValidationError):
        Window(row0=0, col0=0, rows=1001, cols=1)


def test_operation_extra_targets_for_join():
    op = Operation(type="join", target=DataTableTarget(table_id="a"),
                   extra_targets=[DataTableTarget(table_id="b")], params={"how": "left"})
    assert Operation.model_validate_json(op.model_dump_json()).extra_targets[0].table_id == "b"


def test_table_created_delta_uses_version_zero():
    d = TableVersionDelta(table_id="t", from_version=0, to_version=1)
    assert d.from_version == 0
    with pytest.raises(PydanticValidationError):
        TableVersionDelta(table_id="t", from_version=1, to_version=0)


def test_new_error_values_and_result_models():
    Cell(r=0, c=0, v={"k": "err", "e": "#SPILL!"})
    ent = HistoryEntry(id="h", document_id="d", seq=1,
                       operation=Operation(type="edit", target=DataTableTarget(table_id="t")),
                       delta=CellPatchDelta(sheet_id="s", before=[], after=[]),
                       label="x", created_at=datetime.now(timezone.utc))
    r = CellsChangedResult(history_entry=ent, sheet_id="s", cells=[Cell(r=0, c=0)])
    assert CellsChangedResult.model_validate_json(r.model_dump_json()) == r
    CellEditRequest(base_seq=0, edits=[])
    AuthResult(user={"id": "u", "username": "n", "role": "user"}, csrf_token="t")
    StyleInfo(id=1)
    SheetLayout(sheet_id="s")


def test_optional_protocols_exist():
    for proto in (FormattingEngine, StructureEngine, TableStore, ExecContext):
        assert proto is not None
