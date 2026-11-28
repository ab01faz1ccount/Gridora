"""Contract smoke tests. Agents must keep these green; the maintainer owns changes."""
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


# ---- contract v0.4.0 additions ----
from gridora_contracts import (  # noqa: E402
    BlobStore, ColumnarColumn, ColumnarExecContext, ColumnarRange, RangeSnapshotDelta,
)


def test_table_target_version_pointer_optional():
    assert DataTableTarget(table_id="t").version is None
    assert DataTableTarget(table_id="t", version=3).version == 3
    with pytest.raises(PydanticValidationError):
        DataTableTarget(table_id="t", version=0)


def test_columnar_range_roundtrip_and_snapshot_delta():
    rng = Range(sheet_id="s", r0=0, c0=0, r1=1, c1=1)
    data = ColumnarRange(range=rng, columns=[
        ColumnarColumn(kind="num", values=[1.0, None]),
        ColumnarColumn(kind="mixed", values=[{"k": "err", "e": "#N/A"}, None])])
    assert ColumnarRange.model_validate_json(data.model_dump_json()) == data
    d = RangeSnapshotDelta(sheet_id="s", range=rng, before_ref="b1", after_ref="a1", cell_count=4)
    ent = HistoryEntry(id="h", document_id="d", seq=1,
                       operation=Operation(type="sort", target=DataTableTarget(table_id="t")),
                       delta=d, label="x", created_at=datetime.now(timezone.utc))
    assert HistoryEntry.model_validate_json(ent.model_dump_json()).delta.kind == "range_snapshot"


def test_optional_columnar_protocols_exist():
    assert ColumnarExecContext is not None and BlobStore is not None


def test_columnar_engine_protocol_and_contract_patch_version():
    from gridora_contracts import ColumnarEngine, models
    assert ColumnarEngine is not None
    assert models.CONTRACT_VERSION.startswith(("0.6.", "0.7."))


# ---- contract v0.6.0: calendars ----
def test_calendar_models():
    from gridora_contracts import models

    base = dict(id="w", file_id="f", name="n", sheets=[])
    assert models.Workbook(**base).calendar == "jalali"
    assert models.Workbook(**base, calendar="hijri").calendar == "hijri"
    with pytest.raises(PydanticValidationError):
        models.SetCalendarRequest(calendar="mayan")
    col = models.DateColumn(col=0, kind="text", calendar="jalali", header_row=True, dates=9, total=10)
    assert models.DateColumns(sheet_id="s", columns=[col]).columns[0].dates == 9


def test_persian_fold_makes_variants_compare_equal():
    from gridora_contracts.persian import fold_text, variants_of

    same = [
        ("كتاب", "کتاب"), ("علي", "علی"), ("مدرسة", "مدرسه"), ("آب", "اب"), ("أحمد", "احمد"),
        ("مسئله", "مسیله"), ("جزء", "جز"), ("مؤمن", "مومن"), ("می‌روم", "میروم"),
        ("کِتاب", "کتاب"), ("كـتـاب", "کتاب"), ("۱۲۳", "123"), ("١٢٣", "123"), ("a b", "a b"),
        ("ﻻ", "لا"), ("آ", "ا"),
    ]
    for a, b in same:
        assert fold_text(a) == fold_text(b), (a, b)
    assert fold_text("سلام") != fold_text("سلم")  # real letters stay
    assert fold_text("ab") == "ab" and fold_text("") == ""
    assert set(variants_of("ا")) == set("اأإٱآ") and set(variants_of("5")) == set("5۵٥")
    assert variants_of("ـ") == "" and variants_of("x") == "x"


# ---- contract v0.7.0: chart upgrade (additive) ----
def test_chart_spec_saved_before_0_7_still_loads_with_defaults():
    old = {"schema_version": 1, "document_id": "d", "type": "bar", "source": {"kind": "data_table", "table_id": "t"},
           "series": [{"value_col": "a", "category_col": "b", "aggregate": "sum"}], "options": {"stacked": True, "legend": False}}
    spec = ChartSpec.model_validate(old)
    assert spec.options.stacked and not spec.options.legend
    assert spec.filters == [] and spec.sort is None and spec.limit is None and spec.time is None and spec.series_by is None
    assert spec.options.nulls == "gap" and spec.options.orientation == "vertical"


def test_chart_new_models_validate_and_round_trip():
    from gridora_contracts.models import (
        ChartData, ChartFilter, ChartLimit, ChartNote, ChartSeries, ChartSort, ChartTime)
    spec = ChartSpec(document_id="d", type="line", source=DataTableTarget(table_id="t"),
                     series=[ChartSeries(value_col="v", category_col="when", aggregate="median")],
                     filters=[ChartFilter(column="region", op="eq", value="north")],
                     sort=ChartSort(by="value", direction="desc"), limit=ChartLimit(top_n=5, other=True),
                     time=ChartTime(granularity="month", calendar="jalali"))
    assert ChartSpec.model_validate_json(spec.model_dump_json()) == spec
    data = ChartData(categories=["a"], series=[{"name": "v", "values": [1.0]}], categories_kind="category",
                     notes=[ChartNote(code="rows_excluded", params={"count": 2})])
    assert ChartData.model_validate_json(data.model_dump_json()).notes[0].code == "rows_excluded"
    with pytest.raises(Exception):
        ChartLimit(top_n=0)


def test_chart_profile_models_and_optional_protocol():
    from gridora_contracts import ChartProfiler
    from gridora_contracts.models import (
        ChartColumnProfile, ChartProfile, ChartProfileRequest, ChartSeries, ChartSuggestion)
    col = ChartColumnProfile(index=0, name="when", kind="date", nulls=0, distinct=3, min="2025-01-01", max="2025-03-01",
                             looks_like="time")
    prof = ChartProfile(rows=3, columns=[col], suggestions=[ChartSuggestion(
        type="line", series=[ChartSeries(value_col=1, category_col=0, aggregate="sum")], reason="time_and_number")])
    assert ChartProfile.model_validate_json(prof.model_dump_json()) == prof
    assert ChartProfileRequest(source=DataTableTarget(table_id="t")).source.kind == "data_table"

    class Impl:
        def chart_profile(self, source, ctx):  # noqa: ANN001
            return prof
    assert isinstance(Impl(), ChartProfiler) and not isinstance(object(), ChartProfiler)


def test_distribution_chart_types_and_options():
    from gridora_contracts.models import ChartOptions, ChartSeries
    for kind in ("histogram", "boxplot"):
        spec = ChartSpec(document_id="d", type=kind, source=DataTableTarget(table_id="t"),
                         series=[ChartSeries(value_col="v")], options=ChartOptions(bins=10, as_percent=True, outliers=False))
        assert ChartSpec.model_validate_json(spec.model_dump_json()) == spec
    assert ChartOptions().bins is None and ChartOptions().outliers is True and ChartOptions().as_percent is False
    for bad in ({"bins": 1}, {"bins": 201}, {"bin_width": 0}, {"bin_width": -1}):
        with pytest.raises(Exception):
            ChartOptions(**bad)
