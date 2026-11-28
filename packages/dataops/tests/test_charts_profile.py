"""Column profiling and suggestions for the Chart Builder: deterministic facts, hints that never decide."""
from __future__ import annotations

import datetime as dt

import polars as pl
from gridora_contracts import ChartProfiler
from gridora_contracts.models import ChartProfile

from gridora_dataops import create_executor
from gridora_dataops.charts import build_chart_data
from gridora_dataops.charts.profile import profile_frame


def col(p: ChartProfile, name: str):  # type: ignore[no-untyped-def]
    return next(c for c in p.columns if c.name == name)


SALES = pl.DataFrame({
    "region": ["north", "south", "north", "east"] * 5,
    "sales": [120.5, 80.0, 99.9, 45.25, 130.0, 70.5, 88.0, 61.75, 143.0, 52.5, 97.0, 66.0, 110.5, 74.25, 91.0, 58.0, 126.5, 83.0, 102.0, 69.5],
    "age": [23.0, 35.0, 41.0, 28.0, 52.0, 37.0, 44.0, 31.0, 29.0, 60.0, 25.0, 48.0, 33.0, 39.0, 55.0, 27.0, 42.0, 36.0, 30.0, 46.0],
    "order_id": list(range(1, 21)),
})


def test_facts_per_column() -> None:
    p = profile_frame(SALES)
    assert p.rows == 20 and [c.index for c in p.columns] == [0, 1, 2, 3]
    s = col(p, "sales")
    assert (s.kind, s.nulls, s.distinct, s.min, s.max) == ("number", 0, 20, 45.25, 143.0)
    assert s.mean == SALES["sales"].mean()
    r = col(p, "region")
    assert (r.kind, r.distinct, r.looks_like) == ("text", 3, "category")


def test_a_number_is_not_automatically_a_measure() -> None:
    p = profile_frame(SALES)
    assert col(p, "order_id").looks_like == "identifier" and col(p, "order_id").default_aggregate == "count"
    assert col(p, "sales").looks_like == "measure"
    named = profile_frame(pl.DataFrame({"کد": [5.0, 5.0, 6.0], "v": [1.0, 2.0, 3.0]}))
    assert col(named, "کد").looks_like == "identifier"  # by name, even with repeated values


def test_default_aggregate_follows_the_column_name_only_as_a_hint() -> None:
    p = profile_frame(SALES)
    assert col(p, "sales").default_aggregate == "sum" and col(p, "age").default_aggregate == "avg"


def test_nulls_and_blank_text_count_as_empty_and_all_empty_has_no_role() -> None:
    f = pl.DataFrame({"a": ["x", None, "  ", "y"], "b": [None, None, None, None], "c": [1.0, None, 3.0, float("nan")]},
                     schema={"a": pl.String, "b": pl.Float64, "c": pl.Float64})
    p = profile_frame(f)
    assert (col(p, "a").nulls, col(p, "a").distinct) == (2, 2)
    assert col(p, "b").kind == "empty" and col(p, "b").looks_like is None
    assert col(p, "c").max == 3.0  # NaN is not a value


def test_dates_and_text_that_reads_as_dates() -> None:
    f = pl.DataFrame({"d": [dt.date(2025, 1, 1), dt.date(2025, 2, 1)], "j": ["۱۴۰۴/۰۱/۰۱", "1404/02/10"],
                      "g": ["2025-01-01", "2025/03/02"], "t": ["12/05", "hello"], "v": [1.0, 2.0]})
    p = profile_frame(f)
    assert (col(p, "d").kind, col(p, "d").looks_like, col(p, "d").min) == ("date", "time", "2025-01-01")
    assert (col(p, "j").date_text, col(p, "j").looks_like) == ("jalali", "time")
    assert col(p, "g").date_text == "gregorian"
    assert col(p, "t").date_text is None and col(p, "t").looks_like == "category"


def test_suggestions_time_then_category_then_two_numbers() -> None:
    f = pl.DataFrame({"day": [dt.date(2025, 1, i + 1) for i in range(10)], "kind": ["a", "b"] * 5,
                      "x": [3.5, 1.2, 8.8, 4.1, 9.9, 2.2, 7.3, 5.6, 6.4, 0.7], "y": [float(i * 2 % 7) + 0.5 for i in range(10)]})
    kinds = [(s.type, s.reason) for s in profile_frame(f).suggestions]
    assert kinds == [("line", "time_and_number"), ("bar", "category_and_number"), ("pie", "share_of_total"), ("scatter", "two_numbers"),
                     ("histogram", "one_number")]


def test_suggestions_carry_a_complete_mapping_that_builds() -> None:
    p = profile_frame(SALES)
    bar = next(s for s in p.suggestions if s.type == "bar")
    assert [(x.category_col, x.value_col, x.aggregate) for x in bar.series] == [(0, 1, "sum"), (0, 2, "avg")]
    from gridora_contracts.models import ChartSpec, DataTableTarget
    spec = ChartSpec(document_id="d", type=bar.type, source=DataTableTarget(table_id="t"), series=bar.series)
    d = build_chart_data(spec, SALES)
    want = SALES.group_by("region", maintain_order=True).agg(pl.col("sales").sum())["sales"].to_list()
    assert d.categories == ["north", "south", "east"] and d.series[0]["values"] == want and d.series[0]["name"] == "sales"


def test_jalali_text_dates_suggest_a_jalali_time_axis_that_builds() -> None:
    f = pl.DataFrame({"when": ["1404/02/10", "1404/01/01", "1404/01/20"], "v": [1.0, 2.0, 4.0]})
    s = profile_frame(f).suggestions[0]
    assert s.type == "line" and s.time is not None and s.time.calendar == "jalali"
    from gridora_contracts.models import ChartSpec, DataTableTarget
    spec = ChartSpec(document_id="d", type="line", source=DataTableTarget(table_id="t"), series=s.series, time=s.time)
    assert build_chart_data(spec, f).labels == ["1404/01/01", "1404/01/20", "1404/02/10"]


def test_many_categories_get_a_top_n_so_the_chart_is_readable() -> None:
    f = pl.DataFrame({"c": [f"k{i % 80}" for i in range(400)], "v": [1.0] * 400})
    bar = profile_frame(f).suggestions[0]
    assert bar.limit is not None and bar.limit.top_n == 15 and not bar.limit.other


def test_long_date_ranges_start_by_month() -> None:
    f = pl.DataFrame({"day": [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(90)], "v": [1.0] * 90})
    t = profile_frame(f).suggestions[0].time
    assert t is not None and t.granularity == "month"


def test_nothing_to_suggest_is_an_empty_list_not_an_error() -> None:
    assert profile_frame(pl.DataFrame({"a": ["x", "y"]})).suggestions == []
    assert profile_frame(pl.DataFrame({"a": []}, schema={"a": pl.Float64})).rows == 0


def test_unique_whole_numbers_are_not_assumed_to_be_ids_only_a_plain_counter_is() -> None:
    p = profile_frame(pl.DataFrame({"total": [10.0, 40.0, 25.0], "row": [1.0, 2.0, 3.0]}))
    assert col(p, "total").looks_like == "measure" and col(p, "row").looks_like == "identifier"


def test_the_executor_offers_the_optional_protocol() -> None:
    assert isinstance(create_executor({}), ChartProfiler)


def test_a_number_suggests_its_distribution_and_groups_with_enough_rows_suggest_a_box_plot() -> None:
    f = pl.DataFrame({"group": ["a", "b"] * 20, "score": [float(i % 17) + 0.5 for i in range(40)]})
    kinds = [(s.type, s.reason) for s in profile_frame(f).suggestions]
    assert ("histogram", "one_number") in kinds and ("boxplot", "distribution_by_category") in kinds
    box = next(s for s in profile_frame(f).suggestions if s.type == "boxplot")
    assert (box.series[0].category_col, box.series[0].value_col) == (0, 1) and box.series[0].aggregate is None


def test_no_box_plot_suggestion_when_groups_are_too_small_or_too_many() -> None:
    few = pl.DataFrame({"g": ["a", "b", "c", "d"], "v": [1.5, 2.5, 3.5, 4.5]})
    assert all(s.type != "boxplot" for s in profile_frame(few).suggestions)
    many = pl.DataFrame({"g": [f"k{i % 40}" for i in range(400)], "v": [float(i) + 0.5 for i in range(400)]})
    assert all(s.type != "boxplot" for s in profile_frame(many).suggestions)


def test_suggestions_never_exceed_five() -> None:
    f = pl.DataFrame({"day": [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(60)], "g": ["a", "b", "c"] * 20,
                      "x": [float(i % 7) + 0.25 for i in range(60)], "y": [float(i % 11) + 0.75 for i in range(60)]})
    assert len(profile_frame(f).suggestions) <= 5
