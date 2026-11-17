"""The softwiro payroll workbook (Arabic RTL, Excel-made, private/unlicensed): RTL, formulas and
sheet protection are checked separately, as ordered. Skipped when the file is absent."""
from __future__ import annotations

import pytest
from corpus_data import MANIFEST, find_private
from gridora_contracts.models import CellEdit, NumValue, Window

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError


@pytest.fixture(scope="module")
def loaded():
    entry = next(f for f in MANIFEST["private"] if "softwiro" in f["path"])
    p = find_private(entry)
    if p is None:
        pytest.skip("softwiro workbook not present")
    eng = create_engine({})
    h, wb, rep = eng.import_xlsx(p)
    return eng, h, wb, {i.code: i for i in rep.items}


def test_every_sheet_is_rtl_and_reported_as_supported(loaded):
    _eng, _h, wb, codes = loaded
    assert len(wb.sheets) == 7 and all(s.rtl for s in wb.sheets)
    item = codes["xlsx.rtl_view"]
    assert item.status == "supported" and "7 sheet" in item.message
    assert all(any("\u0600" <= ch <= "\u06ff" for ch in s.name) for s in wb.sheets)  # Arabic sheet names kept


def test_formulas_are_read_with_text_and_cached_results(loaded):
    eng, h, wb, codes = loaded
    assert "6806" in codes["xlsx.formulas_not_recalculated"].message
    assert codes["xlsx.formulas_not_recalculated"].status == "partial"
    sheet = next(s for s in wb.sheets if s.name == "الإنتاج اليومي")
    cells = eng.get_cells(h, sheet.id, Window(row0=0, col0=0, rows=1000, cols=11)).cells
    formulas = [c for c in cells if c.f]
    assert len(formulas) > 1000 and all(c.f.startswith("=") for c in formulas)
    assert any("INDEX" in c.f and "MATCH" in c.f for c in formulas)
    assert sum(1 for c in formulas if c.v is not None) > 0.9 * len(formulas)  # cached results are shown


def test_sheet_protection_is_reported_and_preserved_not_enforced(loaded):
    _eng, _h, _wb, codes = loaded
    item = codes["xlsx.sheet_protection"]
    assert item.preserved and item.status == "unsupported" and "5 sheet" in item.message
    assert codes["xlsx.data_validation"].preserved and codes["xlsx.conditional_format"].preserved
    assert codes["xlsx.merged_cells"].preserved and codes["xlsx.hyperlinks"].preserved
    assert codes["xlsx.frozen_panes"].status == "supported" and "4 sheet" in codes["xlsx.frozen_panes"].message
    assert "xlsx.full_calc_on_load" in codes  # the file asks Excel to recalculate on open


def test_editing_a_constant_works_and_undoes_even_on_a_protected_sheet(loaded):
    eng, h, wb, _codes = loaded
    sheet = next(s for s in wb.sheets if s.name == "العمال")
    st = eng._open[h.id].sheets[wb.sheets.index(sheet)]
    st.lazy.materialize_all()
    d = eng.apply_cell_edits(h, sheet.id, [CellEdit(r=500, c=0, value=NumValue(n=1.0))])
    assert d.after[0].v.n == 1.0
    eng.apply_delta(h, d, inverse=True)
    assert st.dirty == set()


def test_shared_or_array_formula_cells_are_refused_with_the_documented_code(loaded):
    eng, h, wb, _codes = loaded
    for i, sheet in enumerate(wb.sheets):
        st = eng._open[h.id].sheets[i]
        st.lazy.materialize_all()
        if st.fkind:
            key = next(iter(st.fkind))
            with pytest.raises(GridoraEngineError) as e:
                eng.apply_cell_edits(h, sheet.id, [CellEdit(r=key >> 14, c=key & 0x3FFF, value=NumValue(n=1.0))])
            assert e.value.reason == "edit.protected_formula_cell" and e.value.code == "validation_failed"
            return
    pytest.skip("this workbook has no shared or array formulas")
