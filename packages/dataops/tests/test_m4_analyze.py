from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import (
    ChartSeries,
    ChartSpec,
    Column,
    DataTableTarget,
    Operation,
    SheetRangeTarget,
    TableVersionDelta,
)

from gridora_dataops import DataOpsExecutor, create_table_store
from gridora_dataops.errors import DataOpsError
from gridora_dataops.ops.group_aggregate import GroupAggregateOp, GroupParams
from gridora_dataops.ops.join import JoinOp, JoinParams
from gridora_dataops.ops.pivot import PivotOp, PivotParams
from gridora_dataops.ops.unpivot import UnpivotOp, UnpivotParams
from gridora_dataops.spec import PlanEnv

SALES = pl.DataFrame({
    "city": ["تهران", "کرج", "تهران", "قم", "کرج", None],
    "kind": ["a", "b", "b", "a", "a", "a"],
    "amount": [10.0, 5.0, None, 7.5, 2.5, 1.0],
    "qty": [1, 2, 3, 4, 5, 6],
})


def ga(df=SALES, **p):  # type: ignore[no-untyped-def]
    return GroupAggregateOp().plan(df, GroupParams.model_validate(p), PlanEnv()).frame


# ------------------------------------------------------------ group_aggregate
def test_group_aggregate_first_appearance_order_and_all_functions() -> None:
    out = ga(by=["city"], aggregations=[{"fn": "sum", "column": "amount"}, {"fn": "avg", "column": "amount"},
                                        {"fn": "count", "column": "amount"}, {"fn": "count"},
                                        {"fn": "count_distinct", "column": "kind"}, {"fn": "min", "column": "qty"},
                                        {"fn": "max", "column": "qty", "name": "biggest"}])
    assert out.columns == ["city", "sum_amount", "avg_amount", "count_amount", "count", "count_distinct_kind", "min_qty", "biggest"]
    rows = {r[0]: r[1:] for r in out.rows()}
    assert list(rows) == ["تهران", "کرج", "قم", None]                    # first appearance, null is its own group
    assert rows["تهران"] == (10.0, 10.0, 1, 2, 2, 1, 3)                  # sum ignores the null, count_amount=1, rows=2
    assert rows["کرج"][:2] == (7.5, 3.75)


def test_group_aggregate_persian_sorted_groups_and_grand_total() -> None:
    out = ga(by=["city"], aggregations=[{"fn": "count"}], sort_groups=True)
    assert out["city"].to_list() == ["تهران", "قم", "کرج", None]          # Persian alphabet: ت < ق < ک, nulls last
    assert ga(by=[], aggregations=[{"fn": "sum", "column": "qty"}]).rows() == [(21,)]


def test_group_aggregate_errors_point_at_the_entry() -> None:
    with pytest.raises(DataOpsError) as e:
        ga(by=["city"], aggregations=[{"fn": "count"}, {"fn": "sum", "column": "kind"}])
    assert (e.value.code, e.value.errors[0].path) == ("type_mismatch", "/params/aggregations/1/column")
    errs = GroupAggregateOp().validate_static(GroupParams.model_validate({"aggregations": [{"fn": "sum"}]}))
    assert errs[0].path == "/params/aggregations/0/column"


def test_output_names_never_collide() -> None:
    out = ga(by=["qty"], aggregations=[{"fn": "sum", "column": "qty", "name": "qty"}])
    assert len(set(out.columns)) == 2


# ------------------------------------------------------------ pivot / unpivot
def pv(df=SALES, **p):  # type: ignore[no-untyped-def]
    return PivotOp().plan(df, PivotParams.model_validate(p), PlanEnv()).frame


def test_pivot_sum_with_fill_and_null_header() -> None:
    out = pv(index=["city"], columns="kind", values="qty", fn="sum", fill_value=0)
    assert out.columns == ["city", "a", "b"] and out["city"].to_list() == ["تهران", "کرج", "قم", None]
    assert out.rows() == [("تهران", 1, 3), ("کرج", 5, 2), ("قم", 4, 0), (None, 6, 0)]
    nulls = pv(SALES.with_columns(pl.when(pl.col("kind") == "b").then(None).otherwise(pl.col("kind")).alias("kind")),
               index=["city"], columns="kind", values="qty")
    assert "(خالی)" in nulls.columns


def test_pivot_rejects_bad_inputs() -> None:
    with pytest.raises(DataOpsError) as e:
        pv(index=["city"], columns="kind", values="kind", fn="sum")
    assert e.value.code == "type_mismatch"
    with pytest.raises(DataOpsError) as e2:
        pv(index=["city"], columns="city", values="qty")
    assert e2.value.code == "invalid_param"
    wide = pl.DataFrame({"i": list(range(300)), "c": [str(n) for n in range(300)], "v": [1] * 300})
    with pytest.raises(DataOpsError) as e3:
        pv(wide, index=["i"], columns="c", values="v")
    assert e3.value.code == "result_too_large"


def test_unpivot_and_mixed_types_become_text_with_a_warning() -> None:
    wide = pl.DataFrame({"id": [1, 2], "a": [1.5, 2.5], "b": [3.0, None]})
    out = UnpivotOp().plan(wide, UnpivotParams.model_validate({"id_columns": ["id"]}), PlanEnv())
    assert out.frame.rows() == [(1, "a", 1.5), (2, "a", 2.5), (1, "b", 3.0), (2, "b", None)] and out.warnings == []
    mixed = pl.DataFrame({"id": [1], "a": [1.5], "b": ["x"]})
    out = UnpivotOp().plan(mixed, UnpivotParams.model_validate({"id_columns": ["id"], "value_name": "id"}), PlanEnv())
    assert out.frame.columns == ["id", "variable", "id_2"] and out.frame["id_2"].to_list() == ["1.5", "x"]
    assert [w.code for w in out.warnings] == ["unpivot_values_as_text"]


# ------------------------------------------------------------ join
LEFT = pl.DataFrame({"id": [1, 2, 3, 4], "name": ["علی", "سارا", "كتاب", "x"]})
RIGHT = pl.DataFrame({"rid": [2.0, 3.0, 3.0, 9.0], "city": ["کرج", "تهران", "قم", "یزد"], "name": ["n2", "n3", "n3b", "n9"]})


def jn(left=LEFT, right=RIGHT, **p):  # type: ignore[no-untyped-def]
    return JoinOp().plan(left, JoinParams.model_validate(p), PlanEnv(extra_frames=[right])).frame


def test_join_kinds_keep_order_and_fill_right_only_keys() -> None:
    inner = jn(left_on=["id"], right_on=["rid"])
    assert inner.rows() == [(2, "سارا", "کرج", "n2"), (3, "كتاب", "تهران", "n3"), (3, "كتاب", "قم", "n3b")]
    assert inner.columns == ["id", "name", "city", "name_right"]
    left = jn(left_on=["id"], right_on=["rid"], how="left")
    assert [r[0] for r in left.rows()] == [1, 2, 3, 3, 4] and left.rows()[0][2:] == (None, None)
    right = jn(left_on=["id"], right_on=["rid"], how="right")
    assert [r[0] for r in right.rows()] == [2, 3, 3, 9]  # the right-only key 9 keeps its value
    full = jn(left_on=["id"], right_on=["rid"], how="full")
    assert sorted(r[0] for r in full.rows()) == [1, 2, 3, 3, 4, 9]


def test_join_is_deterministic() -> None:
    a = jn(left_on=["id"], right_on=["rid"], how="full")
    assert all(a.equals(jn(left_on=["id"], right_on=["rid"], how="full")) for _ in range(5))


def test_join_text_keys_with_variants() -> None:
    right = pl.DataFrame({"k": ["کتاب", "x"], "v": [1, 2]})
    assert jn(right=right, left_on=["name"], right_on=["k"]).height == 1                       # x only
    out = jn(right=right, left_on=["name"], right_on=["k"], ignore_variants=True)
    assert sorted(out["v"].to_list()) == [1, 2]


def test_join_type_and_arity_errors() -> None:
    with pytest.raises(DataOpsError) as e:
        jn(left_on=["name"], right_on=["rid"])
    assert (e.value.code, e.value.errors[0].path) == ("type_mismatch", "/params/right_on/0")
    errs = JoinOp().validate_static(JoinParams.model_validate({"left_on": ["a", "b"], "right_on": ["c"]}))
    assert errs[0].path == "/params/right_on"


# ------------------------------------------------------------ through the executor
@pytest.fixture
def ctx(tmp_path: Path) -> FakeExecContext:
    def path_for(owner: str, tid: str, v: int) -> Path:
        return tmp_path / owner / tid / f"v{v}.parquet"
    store = create_table_store(path_for, new_id=iter(f"t{i}" for i in range(1, 50)).__next__)
    c = FakeExecContext(store=store)
    store.create_from_rows(c, "sales", [Column(name="city", dtype="string"), Column(name="amount", dtype="float64")],
                           [["تهران", 10.0], ["کرج", 5.0], ["تهران", 2.0]])
    store.create_from_rows(c, "cities", [Column(name="city", dtype="string"), Column(name="pop", dtype="int64")],
                           [["تهران", 9], ["قم", 1]])
    return c


def test_group_aggregate_on_a_table_creates_a_new_table_and_leaves_the_source(ctx: FakeExecContext) -> None:
    op = Operation(type="group_aggregate", target=DataTableTarget(table_id="t1"),
                   params={"by": ["city"], "aggregations": [{"fn": "sum", "column": "amount"}]})
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "ok" and res.output == DataTableTarget(table_id="t3")
    assert res.delta == TableVersionDelta(table_id="t3", from_version=0, to_version=1)
    s = ctx.store.for_owner("u1")
    assert s.read_page("t3", 0, 10) == [["تهران", 12.0], ["کرج", 5.0]]
    assert s.versions("u1", "t1") == [1]  # source untouched


def test_join_uses_extra_targets_and_checks_their_columns(ctx: FakeExecContext) -> None:
    ex = DataOpsExecutor()
    op = Operation(type="join", target=DataTableTarget(table_id="t1"), extra_targets=[DataTableTarget(table_id="t2")],
                   params={"left_on": ["city"], "right_on": ["city"], "how": "left"})
    assert ex.validate(op, ctx) == []
    res = ex.apply(op, ctx)
    assert res.status == "ok"
    assert ctx.store.for_owner("u1").read_page("t3", 0, 10) == [["تهران", 10.0, 9], ["کرج", 5.0, None], ["تهران", 2.0, 9]]
    bad = op.model_copy(update={"params": {"left_on": ["city"], "right_on": ["nope"]}})
    assert [(e.code, e.path) for e in ex.validate(bad, ctx)] == [("unknown_column", "/params/right_on/0")]
    missing = op.model_copy(update={"extra_targets": []})
    assert ex.apply(missing, ctx).errors[0].path == "/extra_targets"


def test_join_a_sheet_range_with_a_table(ctx: FakeExecContext) -> None:
    ctx.fill([[txt("city"), txt("rank")], [txt("قم"), num(1)], [txt("تهران"), num(2)]])
    op = Operation(type="join", target=DataTableTarget(table_id="t2"),
                   extra_targets=[SheetRangeTarget(range=ctx.rng(0, 0, 2, 1))],
                   params={"left_on": ["city"], "right_on": ["city"]})
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "ok" and ctx.store.for_owner("u1").read_page("t3", 0, 10) == [["تهران", 9, 2], ["قم", 1, 1]]


def test_preview_of_an_analysis_writes_nothing(ctx: FakeExecContext) -> None:
    op = Operation(type="group_aggregate", target=DataTableTarget(table_id="t1"),
                   params={"by": ["city"], "aggregations": [{"fn": "count"}]})
    pv_ = DataOpsExecutor().preview(op, ctx, 10)
    assert pv_.columns == ["city", "count"] and pv_.total_rows == 2
    assert ctx.store.for_owner("u1").versions("u1", "t1") == [1]
    assert not (ctx.store._file("u1", "t3", 1)).exists()


# ------------------------------------------------------------ chart data
def chart(ctx: FakeExecContext, series: list[ChartSeries], type_: str = "bar", target: str = "t1"):  # type: ignore[no-untyped-def]
    spec = ChartSpec(document_id="d", type=type_, source=DataTableTarget(table_id=target), series=series)
    return DataOpsExecutor().chart_data(spec, ctx)


def test_chart_aggregates_by_category_in_first_appearance_order(ctx: FakeExecContext) -> None:
    d = chart(ctx, [ChartSeries(value_col="amount", category_col="city", aggregate="sum"),
                    ChartSeries(name="n", value_col="amount", category_col="city", aggregate="count")])
    assert d.categories == ["تهران", "کرج"]
    assert d.series == [{"name": "amount", "values": [12.0, 5.0]}, {"name": "n", "values": [2.0, 1.0]}]


def test_chart_without_aggregate_uses_rows_and_column_indexes(ctx: FakeExecContext) -> None:
    d = chart(ctx, [ChartSeries(value_col=1)])
    assert d.categories == [1.0, 2.0, 3.0] and d.series[0]["values"] == [10.0, 5.0, 2.0]
    d2 = chart(ctx, [ChartSeries(value_col="amount", category_col=0)], "line")
    assert d2.categories == ["تهران", "کرج", "تهران"]


def test_chart_errors_are_typed(ctx: FakeExecContext) -> None:
    with pytest.raises(DataOpsError) as e:
        chart(ctx, [ChartSeries(value_col="city")])
    assert (e.value.code, e.value.errors[0].path) == ("type_mismatch", "/series/0/value_col")
    with pytest.raises(DataOpsError) as e2:
        chart(ctx, [ChartSeries(value_col="nope")])
    assert e2.value.code == "unknown_column"
    with pytest.raises(DataOpsError) as e3:
        chart(ctx, [ChartSeries(value_col="amount", category_col="city", aggregate="sum"), ChartSeries(value_col="amount")])
    assert e3.value.code == "chart_series_mismatch"
    with pytest.raises(DataOpsError) as e4:
        chart(ctx, [ChartSeries(value_col="amount", category_col="city")], "scatter")
    assert e4.value.code == "type_mismatch"
    with pytest.raises(DataOpsError) as e5:
        chart(ctx, [ChartSeries(value_col="amount", aggregate="sum")])
    assert e5.value.code == "invalid_param"


def test_chart_from_a_sheet_range_uses_the_first_row_as_header() -> None:
    ctx = FakeExecContext()
    ctx.fill([[txt("m"), txt("v")], [txt("a"), num(1)], [txt("b"), num(2)], [txt("a"), num(3)]])
    spec = ChartSpec(document_id="d", type="pie", source=SheetRangeTarget(range=ctx.rng(0, 0, 3, 1)),
                     series=[ChartSeries(value_col="v", category_col="m", aggregate="sum")])
    d = DataOpsExecutor().chart_data(spec, ctx)
    assert d.categories == ["a", "b"] and d.series == [{"name": "v", "values": [4.0, 2.0]}]


def test_chart_category_cap() -> None:
    from gridora_dataops.charts import MAX_CATEGORIES, build_chart_data
    df = pl.DataFrame({"c": list(range(MAX_CATEGORIES + 1)), "v": [1.0] * (MAX_CATEGORIES + 1)})
    spec = ChartSpec(document_id="d", type="bar", source=DataTableTarget(table_id="x"), series=[ChartSeries(value_col="v", category_col="c")])
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec, df)
    assert e.value.code == "chart_too_many_categories"
