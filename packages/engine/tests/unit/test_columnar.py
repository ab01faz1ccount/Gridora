from __future__ import annotations

import random

import pytest
from gridora_contracts.models import (
    CellEdit,
    ColumnarColumn,
    ColumnarRange,
    ErrValue,
    NumValue,
    Range,
    StrValue,
    Window,
)
from gridora_contracts.protocols import ColumnarEngine
from support import make_xlsx, read_window, sheet_doc

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError

NO_VALUE = {None}


def rng_of(sheet, r0, c0, r1, c1):
    return Range(sheet_id=sheet.id, r0=r0, c0=c0, r1=r1, c1=c1)


def reason(fn, code="validation_failed"):
    with pytest.raises(GridoraEngineError) as e:
        fn()
    assert e.value.code == code
    return e.value.reason


def cell_value_dict(c):
    return None if c.v is None else c.v.model_dump()


def expand(col: ColumnarColumn):
    """Per-cell value dicts (or None) of a columnar column, as get_cells would report them."""
    out = []
    for v in col.values:
        if v is None:
            out.append(None)
        elif col.kind == "mixed":
            out.append(v)
        else:
            k = {"num": ("num", "n"), "str": ("str", "s"), "bool": ("bool", "b"), "date": ("date", "iso")}[col.kind]
            out.append({"k": k[0], k[1]: v})
    return out


def assert_equivalent(eng, h, sheet, r0, c0, r1, c1):
    """read_range_columnar == get_cells over the same range, cell by cell (value, empties)."""
    col = eng.read_range_columnar(h, rng_of(sheet, r0, c0, r1, c1))
    rows = r1 - r0 + 1
    w = {}
    for a in range(r0, r1 + 1, 1000):
        for b in range(c0, c1 + 1, 100):
            win = eng.get_cells(h, sheet.id, Window(row0=a, col0=b, rows=min(1000, r1 - a + 1), cols=min(100, c1 - b + 1)))
            w.update({(c.r, c.c): c for c in win.cells})
    has_f = False
    for ci, column in enumerate(col.columns):
        assert len(column.values) == rows
        for ri, got in enumerate(expand(column)):
            cell = w.get((r0 + ri, c0 + ci))
            exp = cell_value_dict(cell) if cell else None
            assert got == exp, (r0 + ri, c0 + ci, got, exp)
            has_f = has_f or bool(cell and cell.f)
    assert col.has_formulas == has_f or (col.has_formulas and not has_f)  # shared children count as formulas
    return col


def csv_wb(tmp_path, text, **cfg):
    eng = create_engine(cfg)
    p = tmp_path / "t.csv"
    p.write_text(text, encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    return eng, h, wb.sheets[0]


def test_engine_declares_the_optional_protocol():
    assert isinstance(create_engine({}), ColumnarEngine)


def test_column_kinds_and_values(tmp_path):
    eng, h, s = csv_wb(tmp_path, "n,t,b\n1,x,TRUE\n2.5,y,\n,,\n")
    eng.apply_cell_edits(h, s.id, [CellEdit(r=3, c=2, value=ErrValue(e="#N/A"))])
    r = eng.read_range_columnar(h, rng_of(s, 1, 0, 3, 2))
    assert [(c.kind, c.values) for c in r.columns][:2] == [("num", [1.0, 2.5, None]), ("str", ["x", "y", None])]
    assert r.columns[2].kind == "mixed" and r.columns[2].values == [{"k": "str", "s": "TRUE"}, None, {"k": "err", "e": "#N/A"}]
    assert r.has_formulas is False
    e = eng.read_range_columnar(h, rng_of(s, 5, 0, 7, 1))  # entirely outside the data
    assert [(c.kind, c.values) for c in e.columns] == [("empty", [None] * 3)] * 2


def test_bool_date_and_formula_columns_in_xlsx(tmp_path):
    rows = ('<row r="1"><c r="A1" t="b"><v>1</v></c><c r="B1" s="1"><v>45292</v></c><c r="C1"><f>A1</f><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="b"><v>0</v></c><c r="B2" s="1"><v>45293.5</v></c><c r="C2"><f>1+1</f></c></row>'
            '<row r="3"><c r="B3"><v>7</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows)))
    s = wb.sheets[0]
    r = eng.read_range_columnar(h, rng_of(s, 0, 0, 1, 2))
    assert [(c.kind, c.values) for c in r.columns][:2] == [("bool", [True, False]), ("date", ["2024-01-01", "2024-01-02T12:00:00"])]
    assert r.columns[2].kind == "num" and r.columns[2].values == [1.0, None]  # a formula without cached value reads as empty
    assert r.has_formulas is True
    mixed = eng.read_range_columnar(h, rng_of(s, 0, 1, 2, 1))  # a plain number among dates -> exact mixed column
    assert mixed.columns[0].kind == "mixed" and mixed.columns[0].values[2] == {"k": "num", "n": 7.0}
    assert eng.read_range_columnar(h, rng_of(s, 2, 0, 2, 1)).has_formulas is False
    for rng in [(0, 0, 2, 2), (1, 1, 2, 2)]:
        assert_equivalent(eng, h, s, *rng)


def test_shared_formula_children_count_as_formulas(tmp_path):
    rows = ('<row r="1"><c r="A1"><f t="shared" ref="A1:A2" si="0">B1*2</f><v>2</v></c><c r="B1"><v>1</v></c></row>'
            '<row r="2"><c r="A2"><f t="shared" si="0"/><v>4</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "s.xlsx", sheet_doc(rows)))
    s = wb.sheets[0]
    assert eng.read_range_columnar(h, rng_of(s, 1, 0, 1, 0)).has_formulas is True  # only the child cell
    assert eng.read_range_columnar(h, rng_of(s, 0, 1, 1, 1)).has_formulas is False


def test_random_ranges_are_equivalent_to_get_cells_on_a_big_lazy_sheet(tmp_path):
    body = "".join(
        f'<row r="{r}"><c r="A{r}"><v>{r}</v></c><c r="B{r}" t="inlineStr"><is><t>t{r % 7}</t></is></c>'
        + (f'<c r="C{r}" t="b"><v>{r % 2}</v></c>' if r % 3 else f'<c r="C{r}" t="e"><v>#N/A</v></c>')
        + (f'<c r="D{r}" s="1"><v>{45000 + r}</v></c>' if r % 5 else "")
        + f'<c r="E{r}"><f>A{r}*2</f><v>{r * 2}</v></c></row>' for r in range(1, 1500))
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "big.xlsx", sheet_doc(body)))
    s = wb.sheets[0]
    rnd = random.Random(7)
    for _ in range(12):
        r0 = rnd.randrange(0, 1450)
        c0 = rnd.randrange(0, 5)
        assert_equivalent(eng, h, s, r0, c0, min(r0 + rnd.randrange(1, 700), 1600), min(c0 + rnd.randrange(0, 5), 6))


def test_invalid_ranges(tmp_path):
    eng, h, s = csv_wb(tmp_path, "a\n1\n")
    assert reason(lambda: eng.read_range_columnar(h, rng_of(s, 3, 0, 1, 0)), "bad_request") == "range.invalid"
    assert reason(lambda: eng.read_range_columnar(h, rng_of(s, 0, 0, 1_048_576, 0))) == "range.out_of_range"
    small = create_engine({"limits": {"max_cells": 10}})
    p = tmp_path / "s.csv"
    p.write_text("a\n", encoding="utf-8")
    h2, wb2 = small.import_csv(p, CsvImportOptions())
    assert reason(lambda: small.read_range_columnar(h2, rng_of(wb2.sheets[0], 0, 0, 10, 1))) == "range.too_large"
    with pytest.raises(GridoraEngineError) as e:
        eng.read_range_columnar(h, Range(sheet_id="nope", r0=0, c0=0, r1=0, c1=0))
    assert e.value.code == "not_found"


# ------------------------------------------------------------------------------------ write
def write_data(rng, *cols):
    return ColumnarRange(range=rng, columns=[ColumnarColumn(kind=k, values=v) for k, v in cols])


def fp(eng, h, s):
    return {k: (c.v.model_dump_json() if c.v else None, c.f, c.s) for k, c in read_window(eng, h, s).items()}


def test_write_equals_the_same_edits_and_undoes(tmp_path):
    text = "a,b\n1,x\n2,y\n3,z\n"
    e1, h1, s1 = csv_wb(tmp_path, text)
    e2, h2, s2 = csv_wb(tmp_path, text)
    rng1 = rng_of(s1, 1, 0, 4, 1)
    d = e1.write_range_columnar(h1, rng1, write_data(rng1, ("num", [10.0, 2.0, None, 4.5]), ("str", ["x", "Y", "z", None])))
    e2.apply_cell_edits(h2, s2.id, [CellEdit(r=1, c=0, value=NumValue(n=10.0)), CellEdit(r=3, c=0),
                                    CellEdit(r=4, c=0, value=NumValue(n=4.5)), CellEdit(r=2, c=1, value=StrValue(s="Y")),
                                    CellEdit(r=4, c=1)])
    assert fp(e1, h1, s1) == fp(e2, h2, s2)
    assert {(c.r, c.c) for c in d.after} == {(1, 0), (3, 0), (4, 0), (2, 1)}  # unchanged cells are not in the delta
    after = fp(e1, h1, s1)
    e1.apply_delta(h1, d, inverse=True)
    e3, h3, s3 = csv_wb(tmp_path, text)
    assert fp(e1, h1, s1) == fp(e3, h3, s3)  # back to the original
    e1.apply_delta(h1, d, inverse=False)
    assert fp(e1, h1, s1) == after


def test_write_mixed_date_and_error_values(tmp_path):
    rows = '<row r="1"><c r="A1" s="1"><v>45292</v></c><c r="B1"><v>1</v></c></row>'
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "d.xlsx", sheet_doc(rows)))
    s = wb.sheets[0]
    rng = rng_of(s, 0, 0, 1, 1)
    eng.write_range_columnar(h, rng, write_data(rng, ("date", ["2025-02-03", "2025-02-04T06:00:00"]),
                                                ("mixed", [{"k": "err", "e": "#DIV/0!"}, {"k": "str", "s": "ok"}])))
    g = read_window(eng, h, s)
    assert g[0, 0].v.iso == "2025-02-03" and g[0, 0].s == 1 and g[1, 0].v.iso == "2025-02-04T06:00:00"
    assert g[0, 1].v.e == "#DIV/0!" and g[1, 1].v.s == "ok"


def test_write_overwrites_ordinary_formulas_and_refuses_protected_cells(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c><c r="B1"><f>A1*2</f><v>2</v></c><c r="D1"><f t="shared" ref="D1:D2" si="0">A1</f><v>1</v></c></row>'
            '<row r="2"><c r="D2"><f t="shared" si="0"/><v>1</v></c><c r="F2"><f t="array" ref="F2:F3">1</f><v>1</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "f.xlsx", sheet_doc(rows)))
    s = wb.sheets[0]
    rng = rng_of(s, 0, 0, 0, 1)
    d = eng.write_range_columnar(h, rng, write_data(rng, ("num", [5.0]), ("num", [7.0])))
    assert d.before[1].f == "=A1*2" and read_window(eng, h, s)[0, 1].f is None
    for bad in [(0, 3, 0, 3), (1, 3, 1, 3), (2, 5, 2, 5), (0, 0, 3, 5)]:
        r = rng_of(s, *bad)
        cols = [("num", [1.0] * (bad[2] - bad[0] + 1))] * (bad[3] - bad[1] + 1)
        assert reason(lambda r=r, cols=cols: eng.write_range_columnar(h, r, write_data(r, *cols))) == "edit.protected_formula_cell"


def test_write_validation_and_cap(tmp_path):
    eng, h, s = csv_wb(tmp_path, "a,b\n1,2\n", limits={"max_patch_cells": 3})
    rng = rng_of(s, 0, 0, 1, 1)
    before = fp(eng, h, s)
    bad = [
        (write_data(rng, ("num", [1.0, 2.0])), "bad_request"),  # wrong number of columns
        (write_data(rng_of(s, 0, 0, 0, 1), ("num", [1.0]), ("num", [1.0])), "bad_request"),  # range differs
        (write_data(rng, ("num", [1.0, 2.0]), ("num", [1.0])), "bad_request"),  # wrong length
    ]
    for data, code in bad:
        assert reason(lambda d=data: eng.write_range_columnar(h, rng, d), code) == "columnar.shape_mismatch"
    for col, why in [(("num", [float("nan"), 1.0]), "edit.invalid_number"), (("num", ["x", 1.0]), "edit.invalid_number"),
                     (("str", [5, "a"]), "columnar.bad_value"), (("bool", [1, True]), "columnar.bad_value"),
                     (("str", ["x" * 40_000, "a"]), "edit.string_too_long"), (("date", ["2024-01-01", "x"]), "edit.date_needs_format"),
                     (("mixed", [{"k": "zzz"}, None]), "columnar.bad_value"), (("mixed", [{"k": "err", "e": "#NOPE"}, None]), "columnar.bad_value")]:
        assert reason(lambda col=col: eng.write_range_columnar(h, rng, write_data(rng, col, ("num", [1.0, 2.0])))) == why
    assert fp(eng, h, s) == before  # every rejection left the workbook unchanged
    with pytest.raises(GridoraEngineError) as e:
        eng.write_range_columnar(h, rng, write_data(rng, ("num", [1.0, 2.0]), ("num", [3.0, 4.0])))  # 4 changed cells > cap 3
    assert (e.value.code, e.value.reason) == ("operation_conflict", "too_large_for_history")
    assert fp(eng, h, s) == before


def test_write_beyond_the_used_range_extends_it_and_undo_shrinks_it(tmp_path):
    eng, h, s = csv_wb(tmp_path, "a\n1\n")
    rng = rng_of(s, 5, 3, 6, 3)
    d = eng.write_range_columnar(h, rng, write_data(rng, ("str", ["p", "q"])))
    sheet = eng._open[h.id].sheets[0]
    assert (sheet.meta().row_count, sheet.meta().col_count) == (7, 4)
    eng.apply_delta(h, d, inverse=True)
    assert (sheet.meta().row_count, sheet.meta().col_count) == (2, 1)
