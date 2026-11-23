"""Recalculation against Excel's cached values (E7 oracle).

Every formula cell of a corpus workbook is recalculated by the engine (Gregorian calendar, Excel semantics) and
compared with the value Excel stored. Matches must not regress: the private payroll workbook must match in full,
and the public Apache POI files must stay above the recorded ratios (known mismatches are documented in
docs/FORMULA_EVIDENCE.md: array formulas, volatile functions, rare functions, fraction formats)."""
from __future__ import annotations

import collections

import pytest
from corpus_data import MANIFEST, ROOT, find_private

from gridora_engine import create_engine


def _compare(path):
    eng = create_engine({"calendar": "gregorian"})
    h, _wb, _rep = eng.import_xlsx(path)
    st = eng._open[h.id]
    for sh in st.sheets:
        if sh.lazy is not None:
            sh.lazy.materialize_all()
    cached = {}
    for si, sh in enumerate(st.sheets):
        for k in set(sh.formulas) | {k for k, v in sh.fkind.items() if v == 3}:
            cached[(si, k)] = sh.store.get(k >> 14, k & 0x3FFF)
    eng.recalculate(h)
    calc = st.calc
    out = collections.Counter()
    if calc is None:
        return out
    for (si, k), (tag0, val0, _s) in cached.items():
        sh = st.sheets[si]
        tag, val, _ = sh.store.get(k >> 14, k & 0x3FFF)
        if (si << 40) | k in calc.frozen:
            out["frozen"] += 1
            continue
        if tag == 2 and tag0 == 2:
            same = st.strings.get(int(val)) == st.strings.get(int(val0))
        else:
            same = tag == tag0 and (val == val0 or (tag == 1 and abs(val - val0) <= 1e-9 * max(1.0, abs(val0))))
        out["ok" if same else "mismatch"] += 1
    return out


def test_private_payroll_workbook_matches_excel_exactly():
    entry = next(f for f in MANIFEST["private"] if "softwiro" in f["path"])
    p = find_private(entry)
    if p is None:
        pytest.skip("softwiro workbook not present")
    c = _compare(p)
    assert c["ok"] > 6000 and c["mismatch"] == 0 and c["frozen"] == 0, dict(c)


def test_public_files_match_excel_above_recorded_ratio():
    total = collections.Counter()
    for f in MANIFEST["files"]:
        if f["features"].get("formulas", 0) == 0:
            continue
        p = ROOT / f["path"]
        if p.exists():
            total.update(_compare(p))
    judged = total["ok"] + total["mismatch"]
    assert judged > 5000, dict(total)
    assert total["ok"] / judged >= RATIO, dict(total)


RATIO = 0.985
