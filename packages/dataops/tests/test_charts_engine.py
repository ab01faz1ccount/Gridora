"""Chart engine (contract 0.7.0): filters, null-aware aggregation, order, Top N / Other, date axes, notes, pie, scatter.
Every case builds a spec and a plain frame; nothing else is involved."""
from __future__ import annotations

import datetime as dt

import polars as pl
import pytest
from gridora_contracts.models import (
    ChartFilter,
    ChartLimit,
    ChartOptions,
    ChartSeries,
    ChartSort,
    ChartSpec,
    ChartTime,
    DataTableTarget,
)

from gridora_dataops.analytics import NULL_CATEGORY
from gridora_dataops.charts import MAX_SCATTER_POINTS, MAX_SERIES, build_chart_data
from gridora_dataops.charts.common import OTHER_CATEGORY
from gridora_dataops.errors import DataOpsError


def spec(type_: str = "bar", series: list[ChartSeries] | None = None, **kw) -> ChartSpec:  # type: ignore[no-untyped-def]
    return ChartSpec(document_id="d", type=type_, source=DataTableTarget(table_id="t"),
                     series=series or [ChartSeries(value_col="v", category_col="c", aggregate="sum")], **kw)


def build(frame: pl.DataFrame, **kw):  # type: ignore[no-untyped-def]
    return build_chart_data(spec(**kw), frame)


def notes(data) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    return {n.code: n.params for n in data.notes}


SALES = pl.DataFrame({"c": ["b", "a", "b", "c", "a", "b"], "v": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                      "g": ["x", "x", "y", "y", "x", "y"]})


# ---------------------------------------------------------------- aggregation, nulls and zero
def test_sum_keeps_first_appearance_order_and_adds_duplicates() -> None:
    d = build(SALES)
    assert d.categories == ["b", "a", "c"] and d.series[0]["values"] == [10.0, 7.0, 4.0]
    assert d.categories_kind == "category" and d.notes == []


def test_all_empty_group_is_empty_not_zero() -> None:
    f = pl.DataFrame({"c": ["a", "a", "b"], "v": [None, None, 3.0]}, schema={"c": pl.String, "v": pl.Float64})
    d = build(f)
    assert d.series[0]["values"] == [None, 3.0]
    assert notes(d)["empty_values"]["count"] == 1


def test_a_real_zero_stays_zero_and_is_not_reported_as_empty() -> None:
    d = build(pl.DataFrame({"c": ["a", "b"], "v": [0.0, 2.0]}))
    assert d.series[0]["values"] == [0.0, 2.0] and notes(d) == {}


def test_count_of_an_empty_group_is_a_real_zero() -> None:
    f = pl.DataFrame({"c": ["a", "b"], "v": [None, 1.0]}, schema={"c": pl.String, "v": pl.Float64})
    d = build(f, series=[ChartSeries(value_col="v", category_col="c", aggregate="count")])
    assert d.series[0]["values"] == [0.0, 1.0]


def test_nulls_as_zero_only_when_the_user_asks() -> None:
    f = pl.DataFrame({"c": ["a", "b"], "v": [None, 1.0]}, schema={"c": pl.String, "v": pl.Float64})
    d = build(f, options=ChartOptions(nulls="zero"))
    assert d.series[0]["values"] == [0.0, 1.0] and "empty_values" not in notes(d)


@pytest.mark.parametrize("fn,expected", [("avg", 2.5), ("min", 1.0), ("max", 4.0), ("median", 2.5), ("count_distinct", 4.0)])
def test_aggregates(fn: str, expected: float) -> None:
    f = pl.DataFrame({"c": ["a"] * 4, "v": [1.0, 2.0, 3.0, 4.0]})
    assert build(f, series=[ChartSeries(value_col="v", category_col="c", aggregate=fn)]).series[0]["values"] == [expected]  # type: ignore[arg-type]


def test_empty_category_is_its_own_visible_group() -> None:
    f = pl.DataFrame({"c": ["a", None], "v": [1.0, 2.0]})
    assert build(f).categories == ["a", NULL_CATEGORY]


# ------------------------------------------------------------------------------- filters
def test_chart_filters_limit_what_the_chart_reads() -> None:
    d = build(SALES, filters=[ChartFilter(column="g", op="eq", value="x")])
    assert d.categories == ["b", "a"] and d.series[0]["values"] == [1.0, 7.0]


def test_two_filters_are_anded_and_use_the_filter_operation_rules() -> None:
    d = build(SALES, filters=[ChartFilter(column="v", op="ge", value=2), ChartFilter(column="v", op="lt", value=6)])
    assert d.categories == ["a", "b", "c"] and d.series[0]["values"] == [7.0, 3.0, 4.0]  # a:2+5  b:3  c:4


def test_filter_errors_point_at_the_filter() -> None:
    with pytest.raises(DataOpsError) as e:
        build(SALES, filters=[ChartFilter(column="nope", op="eq", value=1)])
    assert e.value.code == "unknown_column" and e.value.errors[0].path == "/filters/0/column"
    with pytest.raises(DataOpsError) as e2:
        build(SALES, filters=[ChartFilter(column="v", op="eq", value="text")])
    assert e2.value.code == "type_mismatch" and e2.value.errors[0].path.startswith("/filters/0")


def test_a_filter_that_removes_everything_gives_an_empty_chart_not_an_error() -> None:
    d = build(SALES, filters=[ChartFilter(column="v", op="gt", value=1000)])
    assert d.categories == [] and d.series[0]["values"] == []


# ------------------------------------------------------------------------ sort, Top N, Other
def test_sort_by_value_desc_and_by_category() -> None:
    assert build(SALES, sort=ChartSort(by="value", direction="desc")).categories == ["b", "a", "c"]
    assert build(SALES, sort=ChartSort(by="value", direction="asc")).categories == ["c", "a", "b"]
    assert build(SALES, sort=ChartSort(by="category", direction="desc")).categories == ["c", "b", "a"]


def test_sort_by_category_is_persian_aware_and_puts_empty_last() -> None:
    f = pl.DataFrame({"c": ["ز", "ب", None, "آ", "پ"], "v": [1.0] * 5})
    assert build(f, sort=ChartSort(by="category")).categories == ["آ", "ب", "پ", "ز", NULL_CATEGORY]


def test_numeric_categories_sort_as_numbers() -> None:
    f = pl.DataFrame({"c": [10.0, 9.0, 100.0], "v": [1.0, 1.0, 1.0]})
    assert build(f, sort=ChartSort(by="category")).categories == [9.0, 10.0, 100.0]


def test_manual_order_puts_listed_categories_first() -> None:
    assert build(SALES, sort=ChartSort(order=["c", "zzz", "b"])).categories == ["c", "b", "a"]


def test_top_n_is_by_value_and_says_so() -> None:
    d = build(SALES, limit=ChartLimit(top_n=2))
    assert d.categories == ["b", "a"] and notes(d)["categories_limited"] == {"shown": 2, "total": 3}


def test_bottom_n() -> None:
    assert build(SALES, limit=ChartLimit(top_n=1, end="bottom")).categories == ["c"]


def test_top_n_other_keeps_the_total() -> None:
    d = build(SALES, limit=ChartLimit(top_n=1, other=True))
    assert d.categories == ["b", OTHER_CATEGORY] and d.series[0]["values"] == [10.0, 11.0]
    assert sum(d.series[0]["values"]) == 21.0 and notes(d)["other_merged"] == {"count": 2}


def test_other_stays_last_even_when_it_is_the_biggest() -> None:
    d = build(SALES, limit=ChartLimit(top_n=1, other=True), sort=ChartSort(by="value", direction="desc"))
    assert d.categories == ["b", OTHER_CATEGORY]
    d2 = build(SALES, limit=ChartLimit(top_n=1, end="bottom", other=True), sort=ChartSort(by="value", direction="desc"))
    assert d2.categories == ["c", OTHER_CATEGORY] and d2.series[0]["values"] == [4.0, 17.0]


def test_other_is_refused_for_averages_instead_of_inventing_a_number() -> None:
    with pytest.raises(DataOpsError) as e:
        build(SALES, series=[ChartSeries(value_col="v", category_col="c", aggregate="avg")], limit=ChartLimit(top_n=1, other=True))
    assert e.value.code == "invalid_param" and e.value.errors[0].path == "/limit/other"


def test_top_n_with_an_explicit_category_sort() -> None:
    d = build(SALES, limit=ChartLimit(top_n=2), sort=ChartSort(by="category"))
    assert d.categories == ["a", "b"]


def test_too_many_categories_is_an_error_with_a_way_out_and_top_n_lifts_it() -> None:
    f = pl.DataFrame({"c": [str(i) for i in range(5001)], "v": [1.0] * 5001})
    with pytest.raises(DataOpsError) as e:
        build(f)
    assert e.value.code == "chart_too_many_categories" and e.value.errors[0].hint
    assert len(build(f, limit=ChartLimit(top_n=10)).categories) == 10


# --------------------------------------------------------------------------- series_by
def test_series_by_makes_one_series_per_group_with_shared_categories() -> None:
    d = build(SALES, series_by="g")
    assert d.categories == ["b", "a", "c"]
    by = {s["name"]: s["values"] for s in d.series}
    assert by == {"x": [1.0, 7.0, None], "y": [9.0, None, 4.0]}


def test_series_by_needs_an_aggregate_and_one_value_column() -> None:
    with pytest.raises(DataOpsError) as e:
        build(SALES, series=[ChartSeries(value_col="v", category_col="c")], series_by="g")
    assert e.value.code == "invalid_param"
    with pytest.raises(DataOpsError):
        build(SALES, series=[ChartSeries(value_col="v", category_col="c", aggregate="sum")] * 2, series_by="g")


def test_too_many_series() -> None:
    f = pl.DataFrame({"c": ["a"] * (MAX_SERIES + 1), "g": [str(i) for i in range(MAX_SERIES + 1)], "v": [1.0] * (MAX_SERIES + 1)})
    with pytest.raises(DataOpsError) as e:
        build(f, series_by="g")
    assert e.value.code == "chart_too_many_series"


# ------------------------------------------------------------------------------- dates
DATES = pl.DataFrame({"d": [dt.date(2025, 4, 30), dt.date(2025, 3, 21), dt.date(2025, 4, 2), None],
                      "v": [1.0, 2.0, 4.0, 8.0]})


def test_a_date_axis_is_chronological_whatever_the_row_order() -> None:
    d = build_chart_data(spec("line", [ChartSeries(value_col="v", category_col="d", aggregate="sum")]), DATES)
    assert d.categories == ["2025-03-21", "2025-04-02", "2025-04-30"] and d.categories_kind == "time"
    assert notes(d)["rows_excluded"] == {"count": 1, "reason": "empty_date"}


def test_month_buckets_gregorian_and_jalali() -> None:
    s = [ChartSeries(value_col="v", category_col="d", aggregate="sum")]
    g = build_chart_data(spec("line", s, time=ChartTime(granularity="month")), DATES)
    assert g.labels == ["2025-03", "2025-04"] and g.series[0]["values"] == [2.0, 5.0]
    j = build_chart_data(spec("line", s, time=ChartTime(granularity="month", calendar="jalali")), DATES)
    # 1404/01 (Farvardin) runs 2025-03-21..04-20, so 04-02 belongs to it; 04-30 is in 1404/02 (Ordibehesht)
    assert j.labels == ["1404/01", "1404/02"] and j.categories == ["2025-03-21", "2025-04-21"] and j.series[0]["values"] == [6.0, 1.0]


def test_jalali_year_boundary_is_not_the_gregorian_one() -> None:
    f = pl.DataFrame({"d": [dt.date(2025, 3, 20), dt.date(2025, 3, 21)], "v": [1.0, 1.0]})
    s = [ChartSeries(value_col="v", category_col="d", aggregate="sum")]
    d = build_chart_data(spec("line", s, time=ChartTime(granularity="year", calendar="jalali")), f)
    assert d.labels == ["1403", "1404"]


def test_jalali_text_dates_in_any_digits_are_read_as_dates_and_ordered_in_time() -> None:
    f = pl.DataFrame({"d": ["۱۴۰۴/۰۱/۰۵", "1403/12/29", "1404/01/01", "oops", ""], "v": [1.0, 2.0, 4.0, 8.0, 16.0]})
    s = [ChartSeries(value_col="v", category_col="d", aggregate="sum")]
    d = build_chart_data(spec("line", s, time=ChartTime(granularity="day", calendar="jalali")), f)
    assert d.labels == ["1403/12/29", "1404/01/01", "1404/01/05"] and d.series[0]["values"] == [2.0, 4.0, 1.0]
    assert notes(d)["dates_unreadable"]["count"] == 1 and notes(d)["dates_unreadable"]["examples"] == ["oops"]
    assert notes(d)["rows_excluded"]["reason"] == "empty_date"


def test_descending_time_sort_and_quarters() -> None:
    s = [ChartSeries(value_col="v", category_col="d", aggregate="sum")]
    d = build_chart_data(spec("line", s, time=ChartTime(granularity="quarter"), sort=ChartSort(by="category", direction="desc")), DATES)
    assert d.labels == ["2025-Q2", "2025-Q1"]


def test_source_order_on_a_time_axis_still_means_chronological() -> None:
    s = [ChartSeries(value_col="v", category_col="d", aggregate="sum")]
    d = build_chart_data(spec("line", s, sort=ChartSort(by="source")), DATES)
    assert d.categories == ["2025-03-21", "2025-04-02", "2025-04-30"]


def test_top_n_on_a_time_axis_is_refused_clearly() -> None:
    s = [ChartSeries(value_col="v", category_col="d", aggregate="sum")]
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec("line", s, limit=ChartLimit(top_n=2)), DATES)
    assert e.value.errors[0].path == "/limit"


def test_text_dates_without_a_time_setting_stay_plain_text() -> None:
    f = pl.DataFrame({"d": ["b", "a"], "v": [1.0, 2.0]})
    assert build(f, series=[ChartSeries(value_col="v", category_col="d", aggregate="sum")]).categories_kind == "category"


# ---------------------------------------------------------------------------------- pie
def test_pie_leaves_out_negative_and_empty_values_and_says_so() -> None:
    f = pl.DataFrame({"c": ["a", "b", "c", "d"], "v": [3.0, -1.0, None, 0.0]}, schema={"c": pl.String, "v": pl.Float64})
    d = build_chart_data(spec("pie"), f)
    assert d.categories == ["a", "d"] and d.series[0]["values"] == [3.0, 0.0]
    assert notes(d)["negative_values"]["count"] == 1 and notes(d)["empty_values"]["count"] == 1


def test_pie_with_nothing_positive_is_an_error_with_a_hint() -> None:
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec("pie"), pl.DataFrame({"c": ["a", "b"], "v": [-1.0, -2.0]}))
    assert e.value.code == "invalid_param" and e.value.errors[0].hint


def test_pie_uses_the_first_series_and_reports_the_rest() -> None:
    two = [ChartSeries(value_col="v", category_col="c", aggregate="sum"), ChartSeries(value_col="v", category_col="c", aggregate="count")]
    d = build_chart_data(spec("pie", two), SALES)
    assert len(d.series) == 1 and notes(d)["extra_series_ignored"] == {"count": 1}


def test_pie_top_n_other() -> None:
    d = build_chart_data(spec("pie", limit=ChartLimit(top_n=2, other=True)), SALES)
    assert d.categories == ["b", "a", OTHER_CATEGORY] and d.series[0]["values"] == [10.0, 7.0, 4.0]


# ------------------------------------------------------------------------------ scatter
XY = pl.DataFrame({"x": [1.0, 2.0, None, 4.0, 5.0], "y": [10.0, None, 30.0, 40.0, 50.0], "g": ["a", "b", "a", "b", "a"]})


def scatter(frame: pl.DataFrame, **kw):  # type: ignore[no-untyped-def]
    return build_chart_data(spec("scatter", [ChartSeries(value_col="y", category_col="x")], **kw), frame)


def test_scatter_keeps_rows_as_they_are_and_reports_incomplete_points() -> None:
    d = scatter(XY)
    assert d.categories == [1.0, 4.0, 5.0] and d.series[0]["values"] == [10.0, 40.0, 50.0]
    assert d.categories_kind == "number" and notes(d)["rows_excluded"] == {"count": 2, "reason": "empty_value"}


def test_scatter_does_not_aggregate_duplicates() -> None:
    d = scatter(pl.DataFrame({"x": [1.0, 1.0], "y": [2.0, 3.0]}))
    assert d.categories == [1.0, 1.0] and d.series[0]["values"] == [2.0, 3.0]


def test_scatter_rejects_an_aggregate_and_a_text_x() -> None:
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec("scatter", [ChartSeries(value_col="y", category_col="x", aggregate="sum")]), XY)
    assert e.value.errors[0].path == "/series/0/aggregate"
    with pytest.raises(DataOpsError) as e2:
        build_chart_data(spec("scatter", [ChartSeries(value_col="y", category_col="g")]), XY)
    assert e2.value.code == "type_mismatch"


def test_scatter_color_groups() -> None:
    d = scatter(XY, series_by="g")
    assert d.categories == [1.0, 4.0, 5.0]
    assert {s["name"]: s["values"] for s in d.series} == {"a": [10.0, None, 50.0], "b": [None, 40.0, None]}


def test_scatter_sampling_is_deterministic_and_stated() -> None:
    n = MAX_SCATTER_POINTS * 3 + 7
    f = pl.DataFrame({"x": [float(i) for i in range(n)], "y": [float(i) for i in range(n)]})
    a, b = scatter(f), scatter(f)
    assert a == b and len(a.categories) <= MAX_SCATTER_POINTS and a.categories[0] == 0.0
    assert notes(a)["sampled"]["total"] == n and notes(a)["sampled"]["kept"] == len(a.categories)


def test_scatter_below_the_limit_is_not_sampled() -> None:
    f = pl.DataFrame({"x": [float(i) for i in range(MAX_SCATTER_POINTS)], "y": [1.0] * MAX_SCATTER_POINTS})
    assert "sampled" not in notes(scatter(f))


# --------------------------------------------------------------------------- contracts
def test_a_chart_type_without_an_adapter_is_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from gridora_dataops.charts.adapters import ADAPTERS
    monkeypatch.delitem(ADAPTERS, "pie")
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec("pie"), SALES)
    assert e.value.code == "not_implemented"


def test_empty_frame_gives_an_empty_chart() -> None:
    d = build(pl.DataFrame({"c": [], "v": []}, schema={"c": pl.String, "v": pl.Float64}))
    assert d.categories == [] and d.series[0]["values"] == []


def test_series_must_still_share_categories() -> None:
    mixed = [ChartSeries(value_col="v", category_col="c", aggregate="sum"), ChartSeries(value_col="v", category_col="g", aggregate="sum")]
    with pytest.raises(DataOpsError) as e:
        build(SALES, series=mixed)
    assert e.value.code == "chart_series_mismatch"
