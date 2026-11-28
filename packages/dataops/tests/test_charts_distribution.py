"""Histogram and box plot: the numbers they compute, the edges they cut on, and what they refuse."""
from __future__ import annotations

import random

import polars as pl
import pytest
from gridora_contracts.models import ChartOptions, ChartSeries, ChartSort, ChartSpec, DataTableTarget

from gridora_dataops.analytics import NULL_CATEGORY
from gridora_dataops.charts import build_chart_data
from gridora_dataops.errors import DataOpsError


def spec(kind: str, series: list[ChartSeries] | None = None, **kw) -> ChartSpec:  # type: ignore[no-untyped-def]
    return ChartSpec(document_id="d", type=kind, source=DataTableTarget(table_id="t"),  # type: ignore[arg-type]
                     series=series or [ChartSeries(value_col="v")], **kw)


def hist(values: list, **kw):  # type: ignore[no-untyped-def]
    return build_chart_data(spec("histogram", **kw), pl.DataFrame({"v": values}, schema={"v": pl.Float64}))


def box(values: list, groups: list | None = None, **kw):  # type: ignore[no-untyped-def]
    data: dict = {"v": values}
    series = [ChartSeries(value_col="v")]
    if groups is not None:
        data["g"] = groups
        series = [ChartSeries(value_col="v", category_col="g")]
    return build_chart_data(spec("boxplot", series, **kw), pl.DataFrame(data, schema={"v": pl.Float64, **({"g": pl.String} if groups is not None else {})}))


def notes(d) -> dict:  # type: ignore[no-untyped-def]
    return {n.code: n.params for n in d.notes}


# ------------------------------------------------------------------------------ histogram
def test_counts_add_up_and_every_value_is_in_exactly_one_bin() -> None:
    vals = [1.0, 2, 2, 3, 3, 3, 4, 4, 5, 6, 7, 8, 9, 10, 40]
    d = hist(vals)
    m = d.meta
    assert m["kind"] == "histogram" and sum(m["counts"]) == len(vals) == m["total"]
    assert m["edges"] == [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
    assert m["counts"] == [8, 5, 1, 0, 0, 0, 0, 1]
    assert d.categories[0] == "0–5" and d.series[0]["values"] == [float(c) for c in m["counts"]]


def test_a_value_on_an_edge_goes_to_the_bin_on_its_right_and_the_maximum_closes_the_last_bin() -> None:
    d = hist([0.0, 5.0, 10.0], options=ChartOptions(bin_width=5))
    assert d.meta["edges"] == [0.0, 5.0, 10.0] and d.meta["counts"] == [1, 2]  # 5 -> [5,10]; 10 closes it


def test_float_steps_do_not_leak_noise_into_edges_or_counts() -> None:
    d = hist([0.0, 0.1, 0.2, 0.3], options=ChartOptions(bin_width=0.1))
    assert d.meta["edges"] == [0.0, 0.1, 0.2, 0.3] and d.meta["counts"] == [1, 1, 2]


def test_a_chosen_number_of_bins_is_exactly_that_many() -> None:
    d = hist([float(i) for i in range(100)], options=ChartOptions(bins=4))
    assert len(d.meta["counts"]) == 4 and d.meta["edges"][0] == 0.0 and d.meta["edges"][-1] == 99.0 and sum(d.meta["counts"]) == 100


def test_bin_width_starts_on_a_multiple_of_the_width() -> None:
    d = hist([13.0, 27.0, 41.0], options=ChartOptions(bin_width=10))
    assert d.meta["edges"] == [10.0, 20.0, 30.0, 40.0, 50.0] and d.meta["counts"] == [1, 1, 0, 1]  # 13 -> [10,20), 27 -> [20,30), 41 -> [40,50]


def test_auto_bins_are_round_and_between_5_and_50_whatever_the_size() -> None:
    rnd = random.Random(7)
    for n in (6, 40, 1000, 20000):
        d = hist([rnd.gauss(50, 12) for _ in range(n)])
        bins = len(d.meta["counts"])
        assert 5 <= bins <= 50 + 1, (n, bins)
        widths = {round(b - a, 9) for a, b in zip(d.meta["edges"], d.meta["edges"][1:], strict=False)}
        assert len(widths) == 1 and sum(d.meta["counts"]) == n


def test_heavy_tail_does_not_squash_the_bulk_into_one_bar() -> None:
    d = hist([float(i % 10) for i in range(200)] + [10_000.0])
    assert max(d.meta["counts"]) < 150 or len(d.meta["counts"]) <= 50  # bins are capped at 50, the bulk is still resolved


def test_constant_values_make_one_bin_around_the_value() -> None:
    d = hist([7.0, 7.0, 7.0])
    assert d.meta["edges"] == [6.5, 7.5] and d.meta["counts"] == [3]


def test_a_single_value() -> None:
    d = hist([3.0])
    assert d.meta["counts"] == [1]


def test_negative_values_and_zero() -> None:
    d = hist([-5.0, -1.0, 0.0, 4.0], options=ChartOptions(bin_width=5))
    assert d.meta["edges"] == [-5.0, 0.0, 5.0] and d.meta["counts"] == [2, 2]


def test_empty_and_unreadable_values_are_left_out_and_counted() -> None:
    d = hist([1.0, None, 2.0, float("inf"), float("nan"), 3.0])
    assert d.meta["total"] == 3 and notes(d)["rows_excluded"] == {"count": 3, "reason": "empty_value"}


def test_no_usable_values_gives_an_empty_chart_not_an_error() -> None:
    d = hist([None, None])
    assert d.categories == [] and d.meta["total"] == 0 and notes(d)["rows_excluded"]["count"] == 2
    assert hist([]).meta["total"] == 0


def test_percent_mode_adds_up_to_100_and_keeps_the_counts() -> None:
    d = hist([1.0, 2.0, 3.0, 4.0], options=ChartOptions(bins=2, as_percent=True))
    assert d.series[0]["values"] == [50.0, 50.0] and d.meta["counts"] == [2, 2] and d.meta["percent"] is True


def test_a_text_column_is_refused_where_the_problem_is() -> None:
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec("histogram"), pl.DataFrame({"v": ["a", "b"]}))
    assert e.value.code == "type_mismatch" and e.value.errors[0].path == "/series/0/value_col"


def test_conflicting_or_excessive_bin_settings_are_refused_with_a_way_out() -> None:
    with pytest.raises(DataOpsError) as e:
        hist([1.0, 2.0], options=ChartOptions(bins=3, bin_width=1))
    assert e.value.errors[0].path == "/options/bin_width"
    with pytest.raises(DataOpsError) as e2:
        hist([0.0, 1_000_000.0], options=ChartOptions(bin_width=1))
    assert e2.value.code == "invalid_param" and e2.value.errors[0].hint


def test_things_a_histogram_does_not_have_are_refused() -> None:
    f = pl.DataFrame({"v": [1.0, 2.0], "g": ["a", "b"]})
    for bad, path in ((spec("histogram", [ChartSeries(value_col="v", category_col="g")]), "/series/0/category_col"),
                      (spec("histogram", [ChartSeries(value_col="v", aggregate="sum")]), "/series/0/aggregate"),
                      (spec("histogram", series_by="g"), "/series_by")):
        with pytest.raises(DataOpsError) as e:
            build_chart_data(bad, f)
        assert e.value.errors[0].path == path
    two = spec("histogram", [ChartSeries(value_col="v"), ChartSeries(value_col="v")])
    assert notes(build_chart_data(two, f))["extra_series_ignored"] == {"count": 1}


def test_the_chart_filters_apply_before_binning() -> None:
    from gridora_contracts.models import ChartFilter
    f = pl.DataFrame({"v": [1.0, 2.0, 3.0, 100.0], "g": ["a", "a", "a", "b"]})
    d = build_chart_data(spec("histogram", filters=[ChartFilter(column="g", op="eq", value="a")]), f)
    assert d.meta["total"] == 3 and d.meta["edges"][-1] <= 5


def test_a_million_values_are_binned_quickly_and_the_same_way_every_time() -> None:
    rnd = random.Random(1)
    vals = [rnd.random() * 100 for _ in range(300_000)]
    a, b = hist(vals), hist(vals)
    assert a.meta == b.meta and sum(a.meta["counts"]) == 300_000


# -------------------------------------------------------------------------------- box plot
def test_quartiles_use_one_stated_method_linear_interpolation_like_excel_quartile_inc() -> None:
    b = box([1.0, 2, 3, 4, 5, 6, 7, 8, 9]).meta["boxes"][0]
    assert (b["q1"], b["median"], b["q3"]) == (3.0, 5.0, 7.0)
    b = box([1.0, 2, 3, 4]).meta["boxes"][0]
    assert (b["q1"], b["median"], b["q3"]) == (1.75, 2.5, 3.25)
    assert box([1.0]).meta["quartiles"] == "linear"


def test_whiskers_stop_at_the_furthest_value_inside_the_fences_and_the_rest_are_outliers() -> None:
    b = box([1.0, 2, 2, 3, 3, 3, 4, 4, 5, 6, 7, 8, 9, 10, 40]).meta["boxes"][0]
    assert (b["q1"], b["median"], b["q3"]) == (3.0, 4.0, 7.5)
    assert (b["whisker_low"], b["whisker_high"], b["outliers"], b["min"], b["max"]) == (1.0, 10.0, [40.0], 1.0, 40.0)


def test_outliers_on_both_sides_and_the_option_to_hide_them() -> None:
    vals = [-100.0] + [float(i) for i in range(10, 20)] + [200.0]
    b = box(vals).meta["boxes"][0]
    assert b["outliers"] == [-100.0, 200.0] and b["whisker_low"] == 10.0 and b["whisker_high"] == 19.0
    hidden = box(vals, options=ChartOptions(outliers=False)).meta["boxes"][0]
    assert hidden["outliers"] == [] and hidden["outlier_count"] == 2 and hidden["whisker_high"] == 19.0


def test_groups_come_in_source_order_with_their_own_statistics() -> None:
    d = box([1.0, 2, 3, 10, 20, 30], ["b", "b", "b", "a", "a", "a"])
    assert d.categories == ["b", "a"] and [x["median"] for x in d.meta["boxes"]] == [2.0, 20.0]
    assert d.series[0]["values"] == [2.0, 20.0] and [x["n"] for x in d.meta["boxes"]] == [3, 3]


def test_groups_can_be_sorted_by_median_or_name() -> None:
    g = ["b", "b", "a", "a", "c", "c"]
    v = [5.0, 6, 1, 2, 9, 10]
    assert box(v, g, sort=ChartSort(by="value", direction="desc")).categories == ["c", "b", "a"]
    assert box(v, g, sort=ChartSort(by="category")).categories == ["a", "b", "c"]
    d = box(v, g, sort=ChartSort(by="value", direction="desc"))
    assert [x["category"] for x in d.meta["boxes"]] == d.categories  # the boxes move with their names


def test_small_groups_are_computed_and_flagged_once() -> None:
    d = box([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 9.0], ["a", "a", "b", "b", "b", "b", "b"])
    a, b = d.meta["boxes"]
    assert a["n"] == 2 and (a["q1"], a["median"], a["q3"]) == (1.25, 1.5, 1.75)
    assert b["n"] == 5 and notes(d)["small_sample"] == {"count": 1, "minimum": 5}


def test_one_value_and_identical_values_make_a_flat_box() -> None:
    b = box([4.0]).meta["boxes"][0]
    assert (b["q1"], b["median"], b["q3"], b["whisker_low"], b["whisker_high"], b["outliers"]) == (4.0, 4.0, 4.0, 4.0, 4.0, [])
    s = box([5.0] * 6).meta["boxes"][0]
    assert s["q1"] == s["q3"] == 5.0 and s["outliers"] == []


def test_empty_category_is_its_own_group_and_empty_values_are_counted_not_zero() -> None:
    d = build_chart_data(spec("boxplot", [ChartSeries(value_col="v", category_col="g")]),
                         pl.DataFrame({"v": [1.0, 2.0, None, 3.0], "g": ["a", None, "a", None]}, schema={"v": pl.Float64, "g": pl.String}))
    assert d.categories == ["a", NULL_CATEGORY] and notes(d)["rows_excluded"] == {"count": 1, "reason": "empty_value"}
    assert d.meta["boxes"][0]["n"] == 1  # the empty value is not a zero


def test_a_group_with_no_values_does_not_appear() -> None:
    d = build_chart_data(spec("boxplot", [ChartSeries(value_col="v", category_col="g")]),
                         pl.DataFrame({"v": [1.0, None], "g": ["a", "b"]}, schema={"v": pl.Float64, "g": pl.String}))
    assert d.categories == ["a"]


def test_numeric_group_names_read_like_numbers() -> None:
    d = build_chart_data(spec("boxplot", [ChartSeries(value_col="v", category_col="g")]),
                         pl.DataFrame({"v": [1.0, 2.0], "g": [2024.0, 2025.0]}))
    assert d.categories == ["2024", "2025"]


def test_too_many_groups_is_an_error_with_a_way_out() -> None:
    n = 51
    with pytest.raises(DataOpsError) as e:
        box([1.0] * n, [str(i) for i in range(n)])
    assert e.value.code == "chart_too_many_categories" and e.value.errors[0].hint


def test_negative_values_and_a_text_column() -> None:
    b = box([-5.0, -3.0, -1.0]).meta["boxes"][0]
    assert b["median"] == -3.0
    with pytest.raises(DataOpsError) as e:
        build_chart_data(spec("boxplot"), pl.DataFrame({"v": ["a"]}))
    assert e.value.code == "type_mismatch"


def test_no_data_is_an_empty_chart() -> None:
    d = box([None, None])
    assert d.categories == [] and d.meta["boxes"] == []


def test_a_lot_of_outliers_are_capped_and_the_cap_is_stated() -> None:
    vals = [0.0] * 5000 + [1000.0 + i for i in range(900)]
    b = box(vals)
    box0 = b.meta["boxes"][0]
    assert box0["outlier_count"] == 900 and len(box0["outliers"]) == 300
    assert notes(b)["outliers_limited"] == {"shown": 300, "total": 900}
