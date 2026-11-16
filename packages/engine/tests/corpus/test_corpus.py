"""Corpus tests (Agent 0 order): every real-world file imports with the right sheet count, cell count
and compatibility report; hostile files are rejected with typed errors without crashing or hanging.

Cell counts are checked against an independent oracle (oracle.py), sheet/formula/error counts and
feature flags against corpus/manifest.json (produced by Agent 0's own scan, not by Excel).
Where the report does NOT contain something the manifest lists, the difference must be explained by
an explicit, verified rule in EXPLAINED below; anything else fails (that would be a lost report item)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from corpus_data import MANIFEST, ROOT, find_private
from gridora_contracts.models import ERROR_CODES
from oracle import cell_facts, defined_names, part_names

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError

GUARD = Path(__file__).with_name("_guard.py")
POI = [f for f in MANIFEST["files"] if f["path"].startswith("apache-poi/")]
HOSTILE = [f for f in MANIFEST["files"] if f["path"].startswith("hostile/")]
PRIVATE = [f for f in MANIFEST.get("private", []) if not f["path"].endswith((".xls", ".csv"))]

# manifest feature -> report code that must be present when the feature is truthy
FEATURE_CODES = {
    "charts": "xlsx.chart", "tables": "xlsx.table", "drawings": "xlsx.drawing", "extlinks": "xlsx.external_link",
    "comments": "xlsx.comments", "media": "xlsx.image", "vba": "xlsx.vba_project", "pivot": "xlsx.pivot_table",
    "cf": "xlsx.conditional_format", "dv": "xlsx.data_validation", "merges": "xlsx.merged_cells",
    "names": "xlsx.defined_name", "formulas": "xlsx.formulas_not_recalculated", "shared": "xlsx.shared_formula",
    "array": "xlsx.array_formula",
}


def explained_drawings_are_legacy_comment_shapes(path: Path, codes: set[str]) -> bool:
    names = part_names(path)
    return (not any(re.match(r"xl/drawings/drawing\d+\.xml$", n) for n in names)
            and any(n.endswith(".vml") for n in names) and "xlsx.comments" in codes)


def explained_names_are_only_filter_bookkeeping(path: Path, codes: set[str]) -> bool:
    return bool(defined_names(path)) and all(n == "_xlnm._FilterDatabase" for n in defined_names(path)) \
        and "xlsx.auto_filter" in codes


def explained_media_is_an_empty_directory(path: Path, codes: set[str]) -> bool:
    return not [n for n in part_names(path) if n.startswith("xl/media/") and not n.endswith("/")]


EXPLAINED = {  # (manifest feature, file basename) -> check that proves nothing important is lost
    ("drawings", "right-to-left.xlsx"): explained_drawings_are_legacy_comment_shapes,
    ("drawings", "DataValidationEvaluations.xlsx"): explained_drawings_are_legacy_comment_shapes,
    ("drawings", "FormulaEvalTestData_Copy.xlsx"): explained_drawings_are_legacy_comment_shapes,
    ("names", "LIBRE_OFFICE-116306-0.xlsx"): explained_names_are_only_filter_bookkeeping,
    ("media", "bug62181.xlsx"): explained_media_is_an_empty_directory,
}


def check_file(path: Path, features: dict, engine=None) -> dict:
    eng = engine or create_engine({})
    t0 = time.perf_counter()
    h, wb, rep = eng.import_xlsx(path)
    t_import = time.perf_counter() - t0
    state = eng._open[h.id]
    t0 = time.perf_counter()
    for s in state.sheets:
        s.lazy.materialize_all()
    t_parse = time.perf_counter() - t0
    codes = {i.code for i in rep.items}
    by_code = {i.code: i for i in rep.items}
    oracle_cells, oracle_errors = cell_facts(path)
    assert state.budget.cells == oracle_cells, "cell count differs from the independent oracle"
    assert t_import < 20 and t_parse < 120  # a generous hang guard, not a performance claim
    assert wb.compat == rep and rep.source == "import" and rep.summary.supported + rep.summary.partial + rep.summary.unsupported == len(rep.items)
    if features:
        assert len(wb.sheets) == features["sheets"]
        if features.get("formulas") is not None:
            n = int(by_code["xlsx.formulas_not_recalculated"].message.split()[1]) if features["formulas"] else 0
            assert n == features["formulas"]
        if features.get("errors") is not None:
            assert features["errors"] == oracle_errors
        assert (wb.date_system == "1904") == bool(features.get("date1904"))
        for key, code in FEATURE_CODES.items():
            if features.get(key) and code not in codes:
                rule = EXPLAINED.get((key, path.name))
                assert rule is not None and rule(path, codes), f"report lost {code} (manifest {key}={features[key]})"
        for code in codes - set(FEATURE_CODES.values()):
            assert code.startswith("xlsx."), code
        for item in rep.items:  # preserved items must never claim to be editable or supported
            if item.preserved:
                assert item.status == "unsupported" and item.editable is False
    eng.close(h)
    return {"import": t_import, "parse": t_parse, "cells": oracle_cells}


@pytest.mark.parametrize("entry", POI, ids=[Path(f["path"]).name for f in POI])
def test_apache_poi_file_imports_with_matching_counts_and_report(corpus_root, entry):
    check_file(ROOT / entry["path"], entry["features"])


@pytest.mark.parametrize("entry", PRIVATE, ids=[Path(f["path"]).name for f in PRIVATE])
def test_private_xlsx_imports_with_matching_counts(corpus_root, entry):
    p = find_private(entry)
    if p is None:
        pytest.skip("private file not present")
    facts = check_file(p, {})
    if p.name.startswith("Product-Sales-Region"):
        assert facts["cells"] == 28149  # plain data, no formulas
        _h, _wb, rep = create_engine({}).import_xlsx(p)
        assert {i.code for i in rep.items} == {"xlsx.full_calc_on_load"}  # nothing else to report
    if p.name.startswith("file_example_XLSX_5000"):
        assert facts["cells"] == 40007


def test_workbook_protection_flag_of_file_example_is_reported(corpus_root):
    entry = next(f for f in MANIFEST["private"] if "file_example_XLSX_5000" in f["path"])
    p = find_private(entry)
    if p is None:
        pytest.skip("private file not present")
    import zipfile

    with zipfile.ZipFile(p) as z:
        has = "workbookProtection" in z.read("xl/workbook.xml").decode()
    _h, _wb, rep = create_engine({}).import_xlsx(p)
    assert has == any(i.code == "xlsx.workbook_protection" for i in rep.items)


@pytest.mark.parametrize("entry", HOSTILE, ids=[Path(f["path"]).name[:48] for f in HOSTILE])
def test_hostile_file_is_rejected_or_handled_without_crash_or_hang(corpus_root, entry):
    p = ROOT / entry["path"]
    proc = subprocess.run([sys.executable, str(GUARD), str(p)], capture_output=True, text=True, timeout=90, check=False)
    assert proc.returncode == 0, proc.stderr[-300:]  # no crash (signal/OOM) and no uncaught exception
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["outcome"] in ("typed", "ok"), out  # "untyped" = an exception outside the typed family
    assert out["secs"] < 30
    if out["outcome"] == "typed":
        assert out["code"] in ERROR_CODES and out["reason"]
        assert str(ROOT) not in out["message"] and p.name not in out["message"]


def test_legacy_xls_gets_a_clear_unsupported_format_error(corpus_root):
    entry = next(f for f in MANIFEST["private"] if f["path"].endswith(".xls"))
    p = find_private(entry)
    if p is None:
        pytest.skip("private file not present")
    with pytest.raises(GridoraEngineError) as e:
        create_engine({}).import_xlsx(p)
    assert (e.value.code, e.value.reason) == ("unsupported_workbook", "xlsx.legacy_xls")
    assert ".xls" in str(e.value) and "not supported" in str(e.value) and ".xlsx" in str(e.value)
    assert p.name not in str(e.value)


def test_password_protected_files_say_so(corpus_root):
    for name in ("protected_passtika.xlsx", "58616.xlsx"):
        with pytest.raises(GridoraEngineError) as e:
            create_engine({}).import_xlsx(ROOT / "hostile" / name)
        assert e.value.reason == "xlsx.encrypted" and "password" in str(e.value)


def test_private_csv_imports_like_an_independent_parse(corpus_root):
    import csv

    p = ROOT / "private" / "open_data_us.csv"
    if not p.exists():
        pytest.skip("private file not present")
    eng = create_engine({})
    h, wb = eng.import_csv(p, CsvImportOptions())
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines(keepends=True)))
    assert eng._open[h.id].budget.cells == sum(1 for r in rows for x in r if x)
    assert (wb.sheets[0].row_count, wb.sheets[0].col_count) == (len(rows), max(len(r) for r in rows))
    assert {i.code for i in wb.compat.items} == {"csv.delimiter_detected"}
