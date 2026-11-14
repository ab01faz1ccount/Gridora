from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from fakes import FakeExecContext, num, txt
from gridora_contracts.models import (
    Column,
    DataTableTarget,
    DateValue,
    ErrValue,
    Operation,
    Range,
    SheetRangeTarget,
    StrValue,
    TableVersionDelta,
)

from gridora_dataops import DataOpsExecutor, ParquetTableStore, create_table_store
from gridora_dataops.errors import DataOpsError
from gridora_dataops.tables.bridge import TableImportPreview


@pytest.fixture
def store(tmp_path: Path) -> ParquetTableStore:
    def path_for(owner: str, table_id: str, version: int) -> Path:
        return tmp_path / owner / table_id / f"v{version}.parquet"
    return create_table_store(path_for, new_id=iter(f"t{i}" for i in range(1, 100)).__next__)


def ctx_with(store: ParquetTableStore) -> FakeExecContext:
    return FakeExecContext(store=store)


def make_table(store: ParquetTableStore, ctx: FakeExecContext, name: str = "T"):  # type: ignore[no-untyped-def]
    cols = [Column(name="name", dtype="string"), Column(name="n", dtype="int64"), Column(name="d", dtype="date")]
    return store.create_from_rows(ctx, name, cols, [["گل", 3, "2024-01-02"], ["آب", 1, "2024-01-01"],
                                                    ["باران", 2, None], ["آب", 1, "2024-01-01"]])


# ------------------------------------------------------------ store
def test_create_read_page_and_schema(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    t = make_table(store, ctx)
    assert (t.id, t.version, t.row_count) == ("t1", 1, 4)
    assert [(c.name, c.dtype) for c in t.columns] == [("name", "string"), ("n", "int64"), ("d", "date")]
    s = store.for_owner("u1")
    assert s.read_page("t1", 0, 2) == [["گل", 3, "2024-01-02"], ["آب", 1, "2024-01-01"]]
    assert s.read_page("t1", 3, 10) == [["آب", 1, "2024-01-01"]]
    assert s.read_page("t1", 0, 0) == []


def test_read_page_sort_is_persian_aware_and_stable(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    s = store.for_owner("u1")
    assert [r[0] for r in s.read_page("t1", 0, 10, sort="name")] == ["آب", "آب", "باران", "گل"]
    assert [r[0] for r in s.read_page("t1", 0, 10, sort="-name")] == ["گل", "باران", "آب", "آب"]
    with pytest.raises(DataOpsError) as e:
        s.read_page("t1", 0, 10, sort="nope")
    assert e.value.code == "unknown_column"


def test_unbound_store_cannot_page(store: ParquetTableStore) -> None:
    make_table(store, ctx_with(store))
    with pytest.raises(DataOpsError) as e:
        store.read_page("t1", 0, 1)
    assert e.value.code == "owner_unknown"


def test_owners_are_isolated(store: ParquetTableStore) -> None:
    make_table(store, ctx_with(store))
    with pytest.raises(DataOpsError) as e:
        store.for_owner("someone-else").read_page("t1", 0, 1)
    assert e.value.code == "table_not_found"


def test_versions_are_immutable_and_numbers_never_reused(store: ParquetTableStore, tmp_path: Path) -> None:
    make_table(store, ctx_with(store))
    s = store.for_owner("u1")
    v1 = (tmp_path / "u1" / "t1" / "v1.parquet").read_bytes()
    dt2 = s.write_version("u1", "t1", pl.DataFrame({"name": ["x"], "n": [1], "d": [None]}), parent=1)
    assert dt2.version == 2
    assert (tmp_path / "u1" / "t1" / "v1.parquet").read_bytes() == v1
    with pytest.raises(DataOpsError) as e:  # writing an existing version number is refused
        s._write_parquet(tmp_path / "u1" / "t1" / "v1.parquet", pl.DataFrame({"a": [1]}))
    assert e.value.code == "version_conflict"
    # restoring v1 then writing again must produce v3, not reuse 2
    s.restore_version("t1", 1)
    assert s.write_version("u1", "t1", pl.DataFrame({"name": ["y"], "n": [2], "d": [None]}), parent=1).version == 3


def test_restore_version_is_a_pointer_swap_and_reports_unavailable(store: ParquetTableStore, tmp_path: Path) -> None:
    make_table(store, ctx_with(store))
    s = store.for_owner("u1")
    s.write_version("u1", "t1", pl.DataFrame({"name": ["x"], "n": [1], "d": [None]}), parent=1)
    files_before = sorted(p.name for p in (tmp_path / "u1" / "t1").iterdir())
    t = s.restore_version("t1", 1)
    assert (t.version, t.row_count) == (1, 4)
    assert sorted(p.name for p in (tmp_path / "u1" / "t1").iterdir()) == files_before  # nothing created
    (tmp_path / "u1" / "t1" / "v1.parquet").unlink()  # compacted away
    with pytest.raises(DataOpsError) as e:
        s.restore_version("t1", 1)
    assert e.value.code == "version_unavailable"
    with pytest.raises(DataOpsError) as e:
        s.read_page("t1", 0, 1, version=1)
    assert e.value.code == "version_unavailable"


def test_crash_during_write_leaves_no_partial_version(store: ParquetTableStore, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    make_table(store, ctx_with(store))
    s = store.for_owner("u1")

    def boom(self, *a, **k):  # type: ignore[no-untyped-def]
        Path(a[0]).write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(pl.DataFrame, "write_parquet", boom)
    with pytest.raises(OSError):
        s.write_version("u1", "t1", pl.DataFrame({"name": ["x"], "n": [1], "d": [None]}), parent=1)
    monkeypatch.undo()
    assert sorted(p.name for p in (tmp_path / "u1" / "t1").iterdir()) == ["table.json", "v1.parquet"]
    assert s.versions("u1", "t1") == [1]


def test_all_contract_dtypes_round_trip(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    cols = [Column(name=n, dtype=d) for n, d in [("i", "int64"), ("f", "float64"), ("b", "bool"), ("s", "string"),
                                                  ("d", "date"), ("t", "datetime"), ("m", "decimal")]]
    rows = [[1, 1.5, True, "فارسی", "2024-03-01", "2024-03-01T10:30:00", Decimal("12.34")],
            [None, None, None, None, None, None, None]]
    t = store.create_from_rows(ctx, "all", cols, rows)
    assert [c.dtype for c in t.columns] == ["int64", "float64", "bool", "string", "date", "datetime", "decimal"]
    got = store.for_owner("u1").read_page(t.id, 0, 10)
    assert got[0] == [1, 1.5, True, "فارسی", "2024-03-01", "2024-03-01T10:30:00", "12.3400000000"]
    assert got[1] == [None] * 7


def test_create_from_rows_rejects_values_that_do_not_fit(store: ParquetTableStore) -> None:
    with pytest.raises(DataOpsError) as e:
        store.create_from_rows(ctx_with(store), "x", [Column(name="n", dtype="int64")], [["abc"]])
    assert e.value.code == "type_mismatch"


# ------------------------------------------------------------ bridge: sheet -> table
def sheet_ctx(store: ParquetTableStore | None = None) -> FakeExecContext:
    ctx = FakeExecContext(store=store)
    ctx.fill([[txt("id"), txt("price"), txt("note"), txt("when")],
              [num(1), num(1.5), txt("الف"), DateValue(iso="2024-01-01")],
              [num(2), num(2), None, DateValue(iso="2024-01-02")],
              [num(3), None, num(7), None]])
    return ctx


def test_import_infers_int_for_whole_numbers_and_float_otherwise(store: ParquetTableStore) -> None:
    ctx = sheet_ctx(store)
    pv = store.sheet_range_to_table(ctx, ctx.rng(0, 0, 3, 3), True, preview=True)
    assert isinstance(pv, TableImportPreview)
    assert {c.name: c.dtype for c in pv.columns} == {"id": "int64", "price": "float64", "note": "string", "when": "date"}
    assert pv.row_count == 3 and pv.rows[0] == [1, 1.5, "الف", "2024-01-01"]


def test_import_mixed_column_becomes_text_with_a_warning(store: ParquetTableStore) -> None:
    ctx = sheet_ctx(store)
    pv = store.sheet_range_to_table(ctx, ctx.rng(0, 0, 3, 3), True, preview=True)
    assert [r[2] for r in pv.rows] == ["الف", None, "7"]
    assert [(w.code, w.location) for w in pv.warnings] == [("mixed_column_types", "note")]


def test_preview_stores_nothing_and_import_creates_a_table(store: ParquetTableStore, tmp_path: Path) -> None:
    ctx = sheet_ctx(store)
    store.sheet_range_to_table(ctx, ctx.rng(0, 0, 3, 3), True, preview=True)
    assert list(tmp_path.iterdir()) == []
    t = store.sheet_range_to_table(ctx, ctx.rng(0, 0, 3, 3), True)
    assert (t.id, t.version, t.row_count, t.name) == ("t1", 1, 3, "Table A1:D4")
    assert ctx.writes == 0  # importing never writes to the sheet


def test_import_error_cells_and_formulas_are_reported_not_fatal(store: ParquetTableStore) -> None:
    ctx = sheet_ctx(store)
    ctx.put(2, 1, ErrValue(e="#N/A"))
    ctx.put(1, 0, num(1), f="=1")
    pv = store.sheet_range_to_table(ctx, ctx.rng(0, 0, 3, 3), True, preview=True)
    assert {w.code for w in pv.warnings} >= {"error_values_dropped", "range_has_formulas"}
    assert pv.rows[1][1] is None


def test_import_without_header_names_columns_deterministically(store: ParquetTableStore) -> None:
    ctx = sheet_ctx(store)
    pv = store.sheet_range_to_table(ctx, ctx.rng(1, 0, 2, 1), False, preview=True)
    assert [c.name for c in pv.columns] == ["column_1", "column_2"]


def test_dtype_override_converts_with_persian_digits_and_reports_failures(store: ParquetTableStore) -> None:
    ctx = FakeExecContext(store=store)
    ctx.fill([[txt("v")], [txt("۱٬۲۳۴")], [txt("٥")], [txt("abc")], [None]])
    pv = store.sheet_range_to_table(ctx, ctx.rng(0, 0, 4, 0), True, {"v": "int64"}, preview=True)
    assert pv.rows == [[1234], [5], [None], [None]]
    assert [w.code for w in pv.warnings] == ["values_set_to_null"]
    with pytest.raises(DataOpsError) as e:
        store.sheet_range_to_table(ctx, ctx.rng(0, 0, 4, 0), True, {"nope": "int64"}, preview=True)
    assert e.value.code == "unknown_column"


# ------------------------------------------------------------ bridge: table -> sheet
def test_table_to_cells_writes_header_and_rows_and_undoes(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    out = FakeExecContext(sheet_id="s2", store=store)
    out.user_id = "u1"
    original = out.snapshot()
    delta = store.table_to_cells("t1", out, Range(sheet_id="s2", r0=0, c0=0, r1=0, c1=0))
    assert out.grid[(0, 0)].v == txt("name") and out.grid[(1, 0)].v == txt("گل") and out.grid[(1, 1)].v == num(3)
    assert out.grid[(1, 2)].v == DateValue(iso="2024-01-02")
    out.apply_delta(delta, inverse=True)
    assert out.snapshot() == original


def test_table_to_cells_never_overwrites_and_honours_the_cap(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    out = FakeExecContext(sheet_id="s2", store=store)
    out.put(2, 1, num(99))
    with pytest.raises(DataOpsError) as e:
        store.table_to_cells("t1", out, Range(sheet_id="s2", r0=0, c0=0, r1=0, c1=0))
    assert e.value.code == "would_overwrite" and out.writes == 0 and out.grid[(2, 1)].v == num(99)
    small = create_table_store(store._path_for, max_patch_cells=5, new_id=lambda: "z")
    with pytest.raises(DataOpsError) as e2:
        small.table_to_cells("t1", FakeExecContext(sheet_id="s3", store=small),
                             Range(sheet_id="s3", r0=0, c0=0, r1=0, c1=0))
    assert e2.value.code == "too_large_for_history"


def test_sheet_to_table_to_sheet_round_trip_preserves_values(store: ParquetTableStore) -> None:
    src = sheet_ctx(store)
    t = store.sheet_range_to_table(src, src.rng(0, 0, 3, 3), True)
    dst = FakeExecContext(sheet_id="s9", store=store)
    store.table_to_cells(t.id, dst, Range(sheet_id="s9", r0=0, c0=0, r1=0, c1=0))
    assert [dst.grid[(1, c)].v for c in range(4)] == [num(1), num(1.5), txt("الف"), DateValue(iso="2024-01-01")]
    assert [dst.grid[(3, c)].v for c in (0, 2)] == [num(3), txt("7")]  # mixed column was text


# ------------------------------------------------------------ operations on data tables
def top(table_id: str, type_: str, **params) -> Operation:  # type: ignore[no-untyped-def]
    return Operation(type=type_, target=DataTableTarget(table_id=table_id), params=params)


def test_sort_on_a_table_creates_a_version_and_undo_is_a_pointer_swap(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    ex = DataOpsExecutor()
    res = ex.apply(top("t1", "sort", keys=[{"column": "name"}]), ctx)
    assert res.status == "ok" and res.delta == TableVersionDelta(table_id="t1", from_version=1, to_version=2)
    s = store.for_owner("u1")
    assert [r[0] for r in s.read_page("t1", 0, 10, version=2)] == ["آب", "آب", "باران", "گل"]
    assert [r[0] for r in s.read_page("t1", 0, 10, version=1)] == ["گل", "آب", "باران", "آب"]  # original untouched
    assert s.restore_version("t1", res.delta.from_version).version == 1  # type: ignore[union-attr]


def test_dedupe_and_filter_on_a_table(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    ex = DataOpsExecutor()
    r1 = ex.apply(top("t1", "remove_duplicates"), ctx)
    assert r1.affected.rows == 3 and r1.delta.to_version == 2  # type: ignore[union-attr]
    r2 = ex.apply(Operation(type="filter", target=DataTableTarget(table_id="t1"),
                            params={"where": {"kind": "condition", "column": "n", "op": "ge", "value": 2}}), ctx)
    assert r2.status == "ok" and r2.affected.rows == 2 and r2.output is None  # in place on a table
    assert any(w.code == "table_version_assumed" for w in r2.warnings)  # target named no version


def test_preview_on_a_table_writes_nothing(store: ParquetTableStore, tmp_path: Path) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    before = sorted(p.name for p in (tmp_path / "u1" / "t1").iterdir())
    pv = DataOpsExecutor().preview(top("t1", "sort", keys=[{"column": "n", "direction": "desc"}]), ctx, 2)
    assert pv.rows[0][1] == 3 and pv.total_rows == 4
    assert sorted(p.name for p in (tmp_path / "u1" / "t1").iterdir()) == before


def test_unknown_column_and_missing_table_are_typed(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx)
    ex = DataOpsExecutor()
    errs = ex.validate(top("t1", "sort", keys=[{"column": "nope"}]), ctx)
    assert [(e.code, e.path) for e in errs] == [("unknown_column", "/params/keys/0/column")]
    res = ex.apply(top("missing", "sort", keys=[{"column": "name"}]), ctx)
    assert res.status == "error" and res.errors[0].code == "table_not_found"


def test_filter_on_a_sheet_creates_a_new_table_and_leaves_the_sheet_alone(store: ParquetTableStore) -> None:
    ctx = FakeExecContext(store=store)
    ctx.fill([[txt("نام"), txt("نمره")], [txt("گل"), num(3)], [txt("آب"), num(1)], [txt("باران"), num(2)]])
    before = ctx.snapshot()
    op = Operation(type="filter", target=SheetRangeTarget(range=ctx.rng(0, 0, 3, 1)),
                   params={"where": {"kind": "condition", "column": "نمره", "op": "gt", "value": 1}})
    res = DataOpsExecutor().apply(op, ctx)
    assert res.status == "ok" and ctx.snapshot() == before and ctx.writes == 0
    assert res.output == DataTableTarget(table_id="t1")
    assert res.delta == TableVersionDelta(table_id="t1", from_version=0, to_version=1)
    s = store.for_owner("u1")
    assert s.read_page("t1", 0, 10) == [["گل", 3], ["باران", 2]]  # whole numbers became int64
    assert s.restore_version("t1", 1).name == "فیلتر"


def test_applying_to_every_target_kind_is_deterministic(store: ParquetTableStore) -> None:
    ctx = ctx_with(store)
    make_table(store, ctx, "A")
    make_table(store, ctx, "B")
    ex = DataOpsExecutor()
    ex.apply(top("t1", "sort", keys=[{"column": "name"}, {"column": "n"}]), ctx)
    ex.apply(top("t2", "sort", keys=[{"column": "name"}, {"column": "n"}]), ctx)
    s = store.for_owner("u1")
    assert s.read_page("t1", 0, 10) == s.read_page("t2", 0, 10)


def test_filter_output_name_and_no_header_option(store: ParquetTableStore) -> None:
    ctx = FakeExecContext(store=store)
    ctx.fill([[num(1), txt("x")], [num(2), txt("y")]])
    op = Operation(type="filter", target=SheetRangeTarget(range=ctx.rng(0, 0, 1, 1)),
                   params={"has_header": False, "where": {"kind": "condition", "column": "column_1", "op": "gt", "value": 1}})
    assert DataOpsExecutor().apply(op, ctx).status == "ok"
    assert store.for_owner("u1").read_page("t1", 0, 5) == [[2, "y"]]
    assert StrValue(s="x")
