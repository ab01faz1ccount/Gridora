from __future__ import annotations

from support import make_xlsx, sheet_doc

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions


def csv_cols(tmp_path, text):
    eng = create_engine({})
    p = tmp_path / "t.csv"
    p.write_text(text, encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    return eng.detect_date_columns(h, wb.sheets[0].id)


def test_jalali_text_column_with_header_and_persian_digits(tmp_path):
    got = csv_cols(tmp_path, "نام,تاریخ,مبلغ\nعلی,1403/01/05,10\nمریم,۱۴۰۳/۰۲/۱۰,20\nرضا,1403-03-01,30\n")
    assert [(d["col"], d["kind"], d["calendar"], d["header_row"]) for d in got] == [(1, "text", "jalali", True)]


def test_gregorian_text_column_and_plain_columns_are_not_dates(tmp_path):
    got = csv_cols(tmp_path, "a,d,n\nx,2024-03-20,5\ny,2024-04-01,6\nz,2025-01-02,7\n")
    assert [(d["col"], d["calendar"]) for d in got] == [(1, "gregorian")]


def test_mostly_text_with_a_few_dates_is_not_a_date_column(tmp_path):
    assert csv_cols(tmp_path, "a\nx\ny\nz\n1403/01/01\nw\n") == []


def test_real_date_cells_by_number_format(tmp_path):
    rows = ('<row r="1"><c r="A1"><v>1</v></c><c r="B1" s="1"><v>45292</v></c></row>'
            '<row r="2"><c r="A2"><v>2</v></c><c r="B2" s="1"><v>45293</v></c></row>')
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows, "")))
    got = eng.detect_date_columns(h, wb.sheets[0].id)
    assert [(d["col"], d["kind"]) for d in got] == [(1, "serial")]


def test_set_calendar_recalculates_dates(tmp_path):
    from gridora_contracts.models import CellEdit, NumValue, Window
    eng = create_engine({})
    p = tmp_path / "t.csv"
    p.write_text("a\n45371\n", encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    s = wb.sheets[0]
    eng.apply_cell_edits(h, s.id, [CellEdit(r=1, c=1, formula="=YEAR(A2)")])

    def year():
        return eng.get_cells(h, s.id, Window(row0=1, col0=1, rows=1, cols=1)).cells[0].v.n

    assert year() == 1403.0  # default calendar is Jalali
    eng.set_calendar(h, "gregorian")
    assert year() == 2024.0
    eng.set_calendar(h, "hijri")
    assert year() == 1445.0
    del NumValue
