from __future__ import annotations

import pytest
from gridora_contracts.models import (
    BoolValue,
    CellEdit,
    CellPatchDelta,
    DateValue,
    ErrValue,
    NumValue,
    SheetStructureDelta,
    StrValue,
)
from support import make_xlsx, read_window, sheet_doc

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError


def num(r, c, n):
    return CellEdit(r=r, c=c, value=NumValue(n=n))


def txt(r, c, s):
    return CellEdit(r=r, c=c, value=StrValue(s=s))


def csv_wb(tmp_path, text="a,b\n1,x\n2,y\n", **cfg):
    eng = create_engine(cfg)
    p = tmp_path / "t.csv"
    p.write_text(text, encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    return eng, h, wb, wb.sheets[0]


def snap(eng, h, sheet):
    return {k: (c.v.model_dump_json() if c.v else None, c.f, c.s) for k, c in read_window(eng, h, sheet).items()}


def reason(fn):
    with pytest.raises(GridoraEngineError) as e:
        fn()
    assert e.value.code == "validation_failed"
    return e.value.reason


def test_edit_returns_before_after_and_undo_redo_restore_exactly(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path)
    original = snap(eng, h, s)
    d = eng.apply_cell_edits(h, s.id, [num(1, 0, 10), txt(2, 1, "سلام"), CellEdit(r=0, c=0), num(5, 3, 7.5)])
    assert isinstance(d, CellPatchDelta) and d.sheet_id == s.id
    assert [(c.r, c.c) for c in d.before] == [(1, 0), (2, 1), (0, 0), (5, 3)]
    assert d.before[0].v.n == 1.0 and d.after[0].v.n == 10.0
    assert d.before[3].v is None and d.after[3].v.n == 7.5  # new cell: empty before
    assert d.after[2].v is None  # cleared
    edited = snap(eng, h, s)
    assert edited[1, 0][0] == '{"k":"num","n":10.0}' and (0, 0) not in edited and edited[2, 1][0].startswith('{"k":"str","s":"سلام"')
    eng.apply_delta(h, d, inverse=True)
    assert snap(eng, h, s) == original
    eng.apply_delta(h, d, inverse=False)
    assert snap(eng, h, s) == edited


def test_all_value_kinds_and_used_range_follows_edits(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path)
    d = eng.apply_cell_edits(h, s.id, [
        CellEdit(r=0, c=5, value=BoolValue(b=True)), CellEdit(r=1, c=5, value=ErrValue(e="#N/A")),
        CellEdit(r=2, c=5, value=ErrValue(e="#SPILL!")), num(10, 7, -1e300)])
    g = read_window(eng, h, s)
    assert [g[0, 5].v.k, g[1, 5].v.e, g[2, 5].v.e, g[10, 7].v.n] == ["bool", "#N/A", "#SPILL!", -1e300]
    assert eng._open[h.id].sheets[0].meta().row_count == 11
    eng.apply_delta(h, d, inverse=True)
    assert eng._open[h.id].sheets[0].meta().row_count == 3 and eng._open[h.id].sheets[0].meta().col_count == 2


def test_duplicate_coordinates_last_wins_and_before_is_the_original(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path)
    d = eng.apply_cell_edits(h, s.id, [num(1, 0, 5), num(1, 0, 6), txt(1, 0, "z")])
    assert len(d.before) == 1 and d.before[0].v.n == 1.0 and d.after[0].v.s == "z"


@pytest.mark.parametrize(
    "edit,why",
    [(CellEdit(r=0, c=0, formula="=1+1"), "edit.formulas_unsupported"),
     (num(1_048_576, 0, 1), "edit.out_of_range"), (num(0, 16_384, 1), "edit.out_of_range"),
     (num(0, 0, float("nan")), "edit.invalid_number"), (num(0, 0, float("inf")), "edit.invalid_number"),
     (txt(0, 0, "x" * 40_000), "edit.string_too_long"),
     (CellEdit(r=0, c=0, value=DateValue(iso="2024-01-01")), "edit.date_needs_format")],
)
def test_invalid_edits_are_rejected_without_changing_anything(tmp_path, edit, why):
    eng, h, _wb, s = csv_wb(tmp_path)
    before = snap(eng, h, s)
    assert reason(lambda: eng.apply_cell_edits(h, s.id, [num(1, 0, 99), edit])) == why
    assert snap(eng, h, s) == before  # the valid first edit was not applied either


def test_patch_size_cap_and_unknown_sheet_and_closed_handle(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path, limits={"max_patch_cells": 2})
    assert reason(lambda: eng.apply_cell_edits(h, s.id, [num(0, 0, 1), num(0, 1, 1), num(0, 2, 1)])) == "too_large_for_history"
    big = CellPatchDelta(sheet_id=s.id, before=[], after=[eng.apply_cell_edits(h, s.id, [num(0, 0, 1)]).after[0]] * 3)
    assert reason(lambda: eng.apply_delta(h, big, inverse=False)) == "too_large_for_history"
    with pytest.raises(GridoraEngineError) as e:
        eng.apply_cell_edits(h, "nope", [num(0, 0, 1)])
    assert e.value.code == "not_found"
    eng.close(h)
    with pytest.raises(GridoraEngineError) as e:
        eng.apply_cell_edits(h, s.id, [num(0, 0, 1)])
    assert e.value.reason == "handle.unknown"


def test_budget_failure_midway_rolls_back_everything(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path, limits={"max_cells": 6})  # 4 cells exist; room for 2 more
    before = snap(eng, h, s)
    with pytest.raises(GridoraEngineError) as e:
        eng.apply_cell_edits(h, s.id, [num(5, 0, 1), num(6, 0, 1), num(7, 0, 1), num(1, 0, 42)])
    assert e.value.reason == "limits.cell_count_exceeded"
    assert snap(eng, h, s) == before and eng._open[h.id].sheets[0].dirty == set()


def test_apply_delta_validation(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path)
    good = eng.apply_cell_edits(h, s.id, [num(0, 0, 1)])
    bad = good.model_copy(update={"after": [good.after[0].model_copy(update={"r": 2_000_000})]})
    assert reason(lambda: eng.apply_delta(h, bad, inverse=False)) == "delta.out_of_range"
    other = SheetStructureDelta(sheet_id=s.id, change={"op": "x"})
    assert reason(lambda: eng.apply_delta(h, other, inverse=False)) == "delta.unsupported_kind"


def test_dirty_tracking_returns_to_clean_when_state_equals_the_import(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path)
    sh = eng._open[h.id].sheets[0]
    eng.apply_cell_edits(h, s.id, [num(1, 0, 9)])
    assert len(sh.dirty) == 1 and len(sh.orig) == 1
    eng.apply_cell_edits(h, s.id, [num(1, 0, 1)])  # typed the original value back
    assert sh.dirty == set() and sh.orig == {}


# --------------------------------------------------------------------------------- XLSX
def xlsx(tmp_path, rows, after="", **kw):
    return make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows, after), **kw)


def test_xlsx_formula_cell_overwritten_by_value_is_restored_by_undo(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>2</v></c><c r="B1"><f>A1*10</f><v>20</v></c><c r="C1"><f>A1+1</f></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(xlsx(tmp_path, rows))
    s = wb.sheets[0]
    original = snap(eng, h, s)
    assert original[0, 1][1] == "=A1*10"
    d = eng.apply_cell_edits(h, s.id, [num(0, 1, 5), num(0, 2, 6)])
    assert d.before[0].f == "=A1*10" and d.before[0].v.n == 20.0 and d.before[1].f == "=A1+1" and d.before[1].v is None
    assert snap(eng, h, s)[0, 1] == ('{"k":"num","n":5.0}', None, None)
    eng.apply_delta(h, d, inverse=True)
    assert snap(eng, h, s) == original
    assert eng._open[h.id].sheets[0].dirty == set()  # identical to the file again


def test_cells_of_shared_and_array_formulas_cannot_be_edited_yet(tmp_path):
    rows = ('<row r="1"><c r="A1"><f t="shared" ref="A1:A3" si="0">B1*2</f><v>2</v></c><c r="B1"><v>1</v></c></row>'
            '<row r="2"><c r="A2"><f t="shared" si="0"/><v>4</v></c></row>'
            '<row r="3"><c r="D3"><f t="array" ref="D3:D5">SUM(B1:B2)</f><v>9</v></c></row>'
            '<row r="5"><c r="D5"><v>9</v></c><c r="E5"><v>1</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(xlsx(tmp_path, rows))
    s = wb.sheets[0]
    for r, c in [(0, 0), (1, 0), (2, 3), (4, 3)]:  # master, child, array master, array member
        assert reason(lambda r=r, c=c: eng.apply_cell_edits(h, s.id, [num(r, c, 1)])) == "edit.protected_formula_cell"
    eng.apply_cell_edits(h, s.id, [num(0, 1, 5), num(4, 4, 2)])  # B1 and E5 are ordinary cells


def test_edit_in_unparsed_block_loads_it_first_and_is_not_clobbered(tmp_path):
    rows = "".join(f'<row r="{r}"><c r="A{r}"><v>{r}</v></c><c r="B{r}"><v>{r}</v></c></row>' for r in range(1, 800))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(xlsx(tmp_path, rows))
    s = wb.sheets[0]
    sh = eng._open[h.id].sheets[0]
    assert sh.lazy.parsed_blocks == {0}  # only the width-probing block
    d = eng.apply_cell_edits(h, s.id, [num(600, 0, -1)])  # row 601 sits in block 2
    assert 2 in sh.lazy.parsed_blocks and d.before[0].v.n == 601.0
    sh.lazy.ensure(0, 800)  # parses the remaining blocks; block 2 must not be parsed again
    g = read_window(eng, h, s, rows=10, row0=598)
    assert g[600, 0].v.n == -1.0 and g[601, 0].v.n == 602.0
    sh.lazy.materialize_all()  # a full re-parse keeps edits (overlay)
    assert read_window(eng, h, s, rows=1, row0=600)[600, 0].v.n == -1.0
    eng.apply_delta(h, d, inverse=True)
    assert read_window(eng, h, s, rows=1, row0=600)[600, 0].v.n == 601.0 and sh.dirty == set()


def test_decoy_row_fallback_after_an_edit_keeps_the_edit(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c></row><!-- <row r="2"> decoy -->'
            '<row r="300"><c r="A300"><v>300</v></c></row><row r="301"><c r="A301"><v>301</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(xlsx(tmp_path, rows))
    s = wb.sheets[0]
    eng.apply_cell_edits(h, s.id, [num(0, 0, 11)])  # parses block 0 -> index mismatch -> full parse
    g = read_window(eng, h, s, rows=400)
    assert g[0, 0].v.n == 11.0 and g[299, 0].v.n == 300.0 and eng._open[h.id].sheets[0].lazy.fell_back


def test_date_edits_use_a_date_format_and_keep_the_cell_style(tmp_path):
    rows = '<row r="1"><c r="A1" s="1"><v>45292</v></c><c r="B1"><v>5</v></c></row>'
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(xlsx(tmp_path, rows))
    s = wb.sheets[0]
    d = eng.apply_cell_edits(h, s.id, [CellEdit(r=0, c=0, value=DateValue(iso="2024-03-01")),
                                       CellEdit(r=0, c=1, value=DateValue(iso="2024-03-02T12:00:00"))])
    g = read_window(eng, h, s)
    assert g[0, 0].v.iso == "2024-03-01" and g[0, 0].s == 1
    assert g[0, 1].v.iso == "2024-03-02T12:00:00" and g[0, 1].s == 1  # gets the workbook's first date format
    eng.apply_delta(h, d, inverse=True)
    g = read_window(eng, h, s)
    assert g[0, 0].v.iso == "2024-01-01" and g[0, 1].v.n == 5.0 and g[0, 1].s is None


def test_delta_survives_json_round_trip_like_the_api_history(tmp_path):
    eng, h, _wb, s = csv_wb(tmp_path)
    original = snap(eng, h, s)
    d = eng.apply_cell_edits(h, s.id, [num(1, 0, 3), txt(0, 1, "ی")])
    d2 = CellPatchDelta.model_validate_json(d.model_dump_json())
    eng.apply_delta(h, d2, inverse=True)
    assert snap(eng, h, s) == original
