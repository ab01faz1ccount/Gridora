from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gridora_contracts.models import (
    Cell,
    CellEdit,
    OperationDescriptor,
    Pipeline,
    PipelineStep,
    SheetRangeTarget,
    StrValue,
    Tool,
    Window,
)
from gridora_contracts.protocols import ExecContext, OperationExecutor, TableStore

from gridora_api.composition.stubs.catalog_stub import catalog
from gridora_api.composition.stubs.executor_stub import StubTableStore
from gridora_api.core.errors import DomainError

from .stubkit import EXEC, ctx_for, op, open_csv, rng


def grid(eng: Any, h: Any, rows: int = 20, cols: int = 5) -> list[list[Any]]:
    out: list[list[Any]] = [[None] * cols for _ in range(rows)]
    for c in eng.get_cells(h, h.sheet_id, Window(row0=0, col0=0, rows=rows, cols=cols)).cells:
        d = c.v.model_dump()
        out[c.r][c.c] = d.get("s", d.get("n", d.get("b")))
    return out


CSV = b"name,city,qty\nreza,tehran,3\nali,shiraz,10\nali,tehran,2\nZed,tehran,7\n"


def test_protocols_and_descriptors_are_valid() -> None:
    assert isinstance(EXEC, OperationExecutor) and isinstance(StubTableStore(), TableStore)
    ds = EXEC.describe_all()
    assert len({d.type for d in ds}) == len(ds) == 3
    for d in ds:
        OperationDescriptor.model_validate(d.model_dump())  # contract-valid
        assert d.params_schema["type"] == "object"
    assert {d.type: d.destructive for d in ds} == {
        "sort": False,
        "find_replace": True,
        "remove_duplicates": True,
    }


@pytest.mark.parametrize("locale", ["fa", "en"])
def test_every_descriptor_key_exists_in_the_catalog(locale: str) -> None:
    cat = catalog(locale)
    for d in EXEC.describe_all():
        for key in (d.label, d.category, d.description):
            assert key in cat, key
    assert set(catalog("fa")) == set(catalog("en"))  # key parity


def test_validate_reports_json_pointers(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    r = rng(h, 0, 0, 4, 2)
    errs = EXEC.validate(op(h, "sort", r, columns=[{"column": 0}, {"column": 9}]))
    assert [(e.code, e.path) for e in errs] == [("param.range", "/params/columns/1/column")]
    assert EXEC.validate(op(h, "sort", r))[0].path == "/params/columns"
    assert EXEC.validate(op(h, "nope", r))[0].path == "/type"
    assert EXEC.validate(op(h, "find_replace", r, find=""))[0].path == "/params/find"
    assert EXEC.validate(op(h, "remove_duplicates", r, columns=[7]))[0].path == "/params/columns"
    assert EXEC.validate(op(h, "sort", r, columns=[{"column": 0}])) == []


def test_sort_multi_key_desc_keeps_header_and_is_undoable(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    ctx = ctx_for(eng, h)
    before = grid(eng, h)
    o = op(
        h, "sort", rng(h, 0, 0, 4, 2), columns=[{"column": 0}, {"column": 2, "descending": True}]
    )
    res = EXEC.apply(o, ctx)
    assert res.status == "ok" and res.delta is not None
    g = grid(eng, h)
    assert g[0][:3] == ["name", "city", "qty"]  # header untouched
    assert [r[0] for r in g[1:5]] == ["ali", "ali", "reza", "Zed"]  # case-folded order
    assert [r[2] for r in g[1:3]] == [10.0, 2.0]  # second key descending
    eng.apply_delta(h, res.delta, inverse=True)
    assert grid(eng, h) == before


def test_preview_does_not_change_anything(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    before = grid(eng, h)
    p = EXEC.preview(op(h, "sort", rng(h, 0, 0, 4, 2), columns=[{"column": 2}]), ctx_for(eng, h), 2)
    assert len(p.rows) == 2 and p.total_rows == 4
    assert grid(eng, h) == before


def test_find_replace_case_and_whole_cell(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    ctx = ctx_for(eng, h)
    r = rng(h, 0, 0, 4, 2)
    res = EXEC.apply(op(h, "find_replace", r, find="TEHRAN", replace="Tehran"), ctx)
    assert res.warnings[0].message == "3 cells changed"
    assert [x[1] for x in grid(eng, h)[1:5]] == ["Tehran", "shiraz", "Tehran", "Tehran"]
    res = EXEC.apply(
        op(h, "find_replace", r, find="ali", replace="A", whole_cell=True, match_case=True), ctx
    )
    assert [x[0] for x in grid(eng, h)[1:5]] == ["reza", "A", "A", "Zed"]
    assert res.delta is not None and res.affected.cells == 2


def test_remove_duplicates_shrinks_and_clears_the_tail(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, b"k,v\na,1\nb,2\na,3\nb,4\nc,5\n")
    before = grid(eng, h)
    res = EXEC.apply(op(h, "remove_duplicates", rng(h, 0, 0, 5, 1), columns=[0]), ctx_for(eng, h))
    g = grid(eng, h)
    assert [r[0] for r in g[1:6]] == ["a", "b", "c", None, None]  # uncovered rows cleared
    assert res.warnings[0].message == "2 rows removed"
    assert res.delta is not None
    eng.apply_delta(h, res.delta, inverse=True)
    assert grid(eng, h) == before


def test_formulas_are_never_silently_flattened() -> None:
    """Review C2.1: a range with formulas is refused, not turned into values."""

    class FormulaCtx:
        user_id, workspace_id = "u", "w"

        def read_range(self, r: Any) -> list[list[Cell | None]]:
            return [
                [Cell(r=0, c=0, v=StrValue(s="x"), f="=A2")],
                [Cell(r=1, c=0, v=StrValue(s="y"))],
            ]

        def write_range(self, *a: Any) -> Any:
            raise AssertionError("must not write")

        def table_store(self) -> Any: ...

    ctx: ExecContext = FormulaCtx()  # type: ignore[assignment]
    o = op(
        type("H", (), {"sheet_id": "s"})(),
        "sort",
        rng(type("H", (), {"sheet_id": "s"})(), 0, 0, 1, 0),
        columns=[{"column": 0}],
    )
    assert [e.code for e in EXEC.validate(o, ctx)] == ["range_has_formulas"]
    with pytest.raises(DomainError) as ei:
        EXEC.apply(o, ctx)
    assert ei.value.code == "validation_failed" and ei.value.details[0].code == "range_has_formulas"


def test_apply_with_invalid_params_changes_nothing(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    before = grid(eng, h)
    with pytest.raises(DomainError) as ei:
        EXEC.apply(op(h, "sort", rng(h, 0, 0, 4, 2), columns=[{"column": 99}]), ctx_for(eng, h))
    assert ei.value.details[0].path == "/params/columns/0/column"
    assert grid(eng, h) == before


def test_pipeline_gives_one_delta_per_step_and_each_undoes(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    start = grid(eng, h)
    p = Pipeline(
        name="p",
        input_kind="sheet_range",
        steps=[
            PipelineStep(type="sort", params={"columns": [{"column": 2}]}),
            PipelineStep(type="find_replace", params={"find": "ali", "replace": "X"}),
        ],
    )
    results = EXEC.run_pipeline(p, SheetRangeTarget(range=rng(h, 0, 0, 4, 2)), ctx_for(eng, h))
    assert len(results) == 2 and all(r.delta is not None for r in results)
    mid = None
    for r in reversed(results):  # per-step undo, newest first
        assert r.delta is not None
        eng.apply_delta(h, r.delta, inverse=True)
        mid = mid or grid(eng, h)
    assert grid(eng, h) == start
    assert mid is not None and mid != start  # state after undoing only step 2: sorted, not replaced


def test_bind_tool_replaces_input_placeholders() -> None:
    tool = Tool(
        name="t",
        pipeline=Pipeline(
            name="p",
            input_kind="sheet_range",
            steps=[PipelineStep(type="sort", params={"columns": [{"column": {"$input": "col"}}]})],
        ),
    )
    bound = EXEC.bind_tool(tool, {"col": 2})
    assert bound.steps[0].params == {"columns": [{"column": 2}]}
    assert tool.pipeline.steps[0].params["columns"][0]["column"] == {"$input": "col"}  # not mutated
    with pytest.raises(DomainError):
        EXEC.bind_tool(tool, {})


def test_unsupported_features_say_so() -> None:
    store = StubTableStore()
    with pytest.raises(DomainError) as e1:
        store.read_page("t", 0, 10)
    assert e1.value.code == "bad_request" and "stub" in e1.value.message
    with pytest.raises(DomainError):
        EXEC.chart_data(None, None)  # type: ignore[arg-type]


def test_edit_via_engine_matches_executor_delta_shape(tmp_path: Path) -> None:
    eng, h, _ = open_csv(tmp_path, CSV)
    d = eng.apply_cell_edits(h, h.sheet_id, [CellEdit(r=1, c=0, value=StrValue(s="q"))])
    assert d.kind == "cell_patch"
