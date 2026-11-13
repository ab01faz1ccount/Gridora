from __future__ import annotations

import pytest
from conftest import cells_of

from gridora_engine.errors import GridoraEngineError


def codes(wb):
    return {i.code for i in wb.compat.items}


def test_basic_types_and_used_range(engine, load):
    h, wb = load(b"name,qty,price\nab,3,1.5\ncd,,2e3\n")
    got = cells_of(engine, h, wb)
    assert got[(0, 0)] == "name" and got[(1, 1)] == 3.0 and got[(1, 2)] == 1.5
    assert got[(2, 2)] == 2000.0 and (2, 1) not in got
    s = wb.sheets[0]
    assert (s.row_count, s.col_count) == (3, 3) and s.name == "Sheet1" and s.rtl is False


def test_infer_types_off_keeps_everything_text(engine, load):
    h, wb = load(b"1,2\n3,x\n", infer_types=False)
    assert cells_of(engine, h, wb) == {(0, 0): "1", (0, 1): "2", (1, 0): "3", (1, 1): "x"}


def test_quoted_newlines_and_escaped_quotes(engine, load):
    h, wb = load(b'a,"line1\nline2","say ""hi"""\r\n1,2,3\r\n')
    got = cells_of(engine, h, wb)
    assert got[(0, 1)] == "line1\nline2" and got[(0, 2)] == 'say "hi"' and got[(1, 2)] == 3.0


def test_blank_rows_keep_positions_and_trailing_blank_rows_are_dropped(engine, load):
    h, wb = load(b"a\n\n\nb\n\n\n")
    assert cells_of(engine, h, wb) == {(0, 0): "a", (3, 0): "b"}
    assert wb.sheets[0].row_count == 4


def test_ragged_rows(engine, load):
    h, wb = load(b"a,b,c\n1\n1,2,3,4\n")
    assert wb.sheets[0].col_count == 4
    assert cells_of(engine, h, wb)[(2, 3)] == 4.0


def test_delimiter_detection(engine, load):
    for delim in (";", "\t", "|"):
        data = f"a{delim}b{delim}c\n1{delim}2{delim}3\n4{delim}5{delim}6\n".encode()
        h, wb = load(data)
        assert cells_of(engine, h, wb)[(2, 2)] == 6.0
        assert "csv.delimiter_detected" in codes(wb)
    h, wb = load(b"a;b\n1;2\n", delimiter=";")
    assert "csv.delimiter_detected" not in codes(wb)
    h, wb = load(b"one column only\nsecond\n")
    assert wb.sheets[0].col_count == 1


def test_delimiter_option_validated(load):
    with pytest.raises(GridoraEngineError) as e:
        load(b"a,b\n", delimiter=",,")
    assert e.value.reason == "csv.delimiter_invalid"


def test_persian_digits_become_numbers(engine, load):
    h, wb = load("a,b,c,d\n۱۲۳,٤٥٦,۱٬۲۳۴٫۵,سلام ۱۲\n".encode())
    got = cells_of(engine, h, wb)
    assert got[(1, 0)] == 123.0 and got[(1, 1)] == 456.0 and got[(1, 2)] == 1234.5
    assert got[(1, 3)] == "سلام ۱۲"  # text with digits is untouched
    item = next(i for i in wb.compat.items if i.code == "csv.persian_digits_normalized")
    assert item.status == "partial" and "3" in item.message


def test_identifiers_stay_text(engine, load):
    h, wb = load(
        "a\n09121234567\n+989121234567\n1234567890123456\n007\n۰۹۱۲۳۴۵۶۷۸۹\n0.5\n12.50\n".encode()
    )
    got = cells_of(engine, h, wb)
    assert [got[(r, 0)] for r in range(1, 5)] == [
        "09121234567", "+989121234567", "1234567890123456", "007",
    ]
    assert got[(5, 0)] == "۰۹۱۲۳۴۵۶۷۸۹"  # Persian digits with a leading zero: original kept
    assert got[(6, 0)] == 0.5 and got[(7, 0)] == 12.5
    assert "csv.numeric_like_kept_as_text" in codes(wb)


def test_utf8_bom_and_plain_utf8_are_certain(engine, load):
    for data in ("\ufeffa,b\nسلام,1\n".encode(), "a,b\nسلام,1\n".encode()):
        h, wb = load(data)
        assert cells_of(engine, h, wb)[(1, 0)] == "سلام"
        assert "csv.encoding_guessed" not in codes(wb)


def test_windows1256_detected_and_reported(engine, load):
    # Windows-1256 has Arabic yeh (U+064A) but no Persian yeh or Persian digits.
    h, wb = load("نام,سن\nعلي,25\nمريم,30\n".encode("cp1256"))
    got = cells_of(engine, h, wb)
    assert got[(1, 0)] == "علي" and got[(2, 0)] == "مريم" and got[(2, 1)] == 30.0
    assert "csv.encoding_guessed" in codes(wb)


def test_latin_fallback_is_reported(engine, load):
    _h, wb = load(b"caf\xe9,na\xefve\n1,2\n")
    assert "csv.encoding_guessed" in codes(wb)


def test_explicit_encoding_wins_and_is_validated(engine, load):
    h, wb = load("سلام".encode("cp1256"), encoding="windows-1256")
    assert cells_of(engine, h, wb)[(0, 0)] == "سلام"
    assert "csv.encoding_guessed" not in codes(wb)
    with pytest.raises(GridoraEngineError) as e:
        load(b"x", encoding="rot13")
    assert e.value.code == "bad_request" and e.value.reason == "csv.encoding_unsupported"


def test_binary_content_rejected(load):
    with pytest.raises(GridoraEngineError) as e:
        load(b"a,b\n\x00\x01\x02,3\n")
    assert e.value.code == "unsupported_media_type"


def test_field_and_size_limits(tmp_path):
    from gridora_contracts.protocols import WorkbookEngine  # noqa: F401

    from gridora_engine import create_engine
    from gridora_engine.csvio.options import CsvImportOptions

    p = tmp_path / "x.csv"
    p.write_text("a\n" + "x" * 40_000 + "\n", encoding="utf-8")
    with pytest.raises(GridoraEngineError) as e:
        create_engine({}).import_csv(p, CsvImportOptions())
    assert e.value.reason == "csv.field_too_long"

    p.write_text("a,b\n1,2\n", encoding="utf-8")
    eng = create_engine({"limits": {"max_file_bytes": 3}})
    with pytest.raises(GridoraEngineError) as e:
        eng.import_csv(p, CsvImportOptions())
    assert e.value.code == "file_too_large"

    eng = create_engine({"limits": {"max_cells": 3}})
    with pytest.raises(GridoraEngineError) as e:
        eng.import_csv(p, CsvImportOptions())
    assert e.value.reason == "limits.cell_count_exceeded"

    eng = create_engine({"limits": {"max_cols": 1}})
    with pytest.raises(GridoraEngineError) as e:
        eng.import_csv(p, CsvImportOptions())
    assert e.value.reason == "csv.too_many_columns"


def test_errors_never_leak_paths(tmp_path):
    from gridora_engine import create_engine
    from gridora_engine.csvio.options import CsvImportOptions

    secret = tmp_path / "very-secret-name.csv"
    with pytest.raises(GridoraEngineError) as e:  # file does not exist
        create_engine({}).import_csv(secret, CsvImportOptions())
    assert "secret" not in str(e.value) and str(tmp_path) not in str(e.value)


def test_unknown_sheet_and_closed_handle(engine, load):
    from gridora_contracts.models import Window

    h, wb = load(b"a\n")
    with pytest.raises(GridoraEngineError) as e:
        engine.get_cells(h, "nope", Window(row0=0, col0=0, rows=1, cols=1))
    assert e.value.code == "not_found"
    engine.close(h)
    with pytest.raises(GridoraEngineError) as e:
        engine.get_cells(h, wb.sheets[0].id, Window(row0=0, col0=0, rows=1, cols=1))
    assert e.value.reason == "handle.unknown"


def test_window_offsets_cross_chunk_boundary(engine, load):
    rows = "\n".join(f"{i},r{i}" for i in range(600)).encode()
    h, wb = load(rows)
    from gridora_contracts.models import Window

    w = engine.get_cells(h, wb.sheets[0].id, Window(row0=250, col0=0, rows=10, cols=2))
    assert [(c.r, c.c) for c in w.cells][:4] == [(250, 0), (250, 1), (251, 0), (251, 1)]
    assert w.cells[-1].v.s == "r259"


def test_export_roundtrip_and_bom(engine, load, tmp_path):
    h, wb = load("a,b\nسلام,1.5\n2,x\n".encode())
    out = tmp_path / "o.csv"
    engine.export_csv(h, wb.sheets[0].id, out)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    h2, wb2 = load(raw)
    assert cells_of(engine, h2, wb2) == cells_of(engine, h, wb)


def test_export_neutralizes_formula_text(engine, load, tmp_path):
    h, wb = load(b'a\n"=1+1"\n"@x"\n"-abc"\n-5\n')
    out = tmp_path / "o.csv"
    engine.export_csv(h, wb.sheets[0].id, out)
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert lines[1:] == ["'=1+1", "'@x", "'-abc", "-5"]  # numeric -5 is never touched
    rep = engine.last_export_report(h)
    assert rep.source == "export" and "3" in rep.items[0].message


def test_export_neutralization_can_be_disabled_and_encoding_chosen(load, tmp_path):
    from gridora_engine import create_engine

    eng = create_engine({"csv_neutralize_formulas": False, "csv_export_encoding": "windows-1256"})
    from gridora_engine.csvio.options import CsvImportOptions

    p = tmp_path / "i.csv"
    p.write_text("a\n=1+1\nسلام\n", encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    out = tmp_path / "o.csv"
    eng.export_csv(h, wb.sheets[0].id, out)
    assert out.read_bytes().decode("cp1256").splitlines()[1:] == ["=1+1", "سلام"]
    assert eng.last_export_report(h).items == []


def test_export_unencodable_character_fails_cleanly(tmp_path):
    from gridora_engine import create_engine
    from gridora_engine.csvio.options import CsvImportOptions

    eng = create_engine({"csv_export_encoding": "windows-1256"})
    p = tmp_path / "i.csv"
    p.write_text("日本語\n", encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    out = tmp_path / "o.csv"
    with pytest.raises(GridoraEngineError) as e:
        eng.export_csv(h, wb.sheets[0].id, out)
    assert e.value.reason == "csv.unencodable_character"
    assert not out.exists() and not (tmp_path / "o.csv.part").exists()


def test_export_persian_yeh_is_not_silently_replaced_in_windows1256(tmp_path):
    from gridora_engine import create_engine
    from gridora_engine.csvio.options import CsvImportOptions

    eng = create_engine({"csv_export_encoding": "windows-1256"})
    p = tmp_path / "i.csv"
    p.write_text("علی\n", encoding="utf-8")  # Persian yeh U+06CC: not representable
    h, wb = eng.import_csv(p, CsvImportOptions())
    with pytest.raises(GridoraEngineError) as e:
        eng.export_csv(h, wb.sheets[0].id, tmp_path / "o.csv")
    assert e.value.reason == "csv.unencodable_character"
