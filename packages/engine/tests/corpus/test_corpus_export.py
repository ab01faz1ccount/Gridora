"""Export round trip on every real corpus file (Review 4: E6).

For each file: import, apply deterministic value edits on every sheet, export, re-import with a
fresh engine and require (1) identical cell contents (fingerprint of every cell of every sheet),
(2) only the expected parts changed, each only in the expected way, (3) inside an edited sheet only
the rows that contain edits differ, byte for byte. A secondary oracle (LibreOffice) must open the
output and show an edited cell."""
from __future__ import annotations

import hashlib
import random
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from corpus_data import MANIFEST, ROOT, find_private
from gridora_contracts.models import CellEdit, NumValue, StrValue, Window

from gridora_engine import create_engine
from gridora_engine.errors import GridoraEngineError

POI = [f["path"] for f in MANIFEST["files"] if f["path"].startswith("apache-poi/")]
PRIVATE = [f for f in MANIFEST.get("private", []) if f["path"].endswith(".xlsx")]
ROW = re.compile(rb'<row\b[^>]*?\br="(\d+)"')


def parts_of(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist() if not i.filename.endswith("/")}


def fingerprint(eng, h) -> str:
    digest = hashlib.sha256()
    for sheet in eng._open[h.id].sheets:
        sheet.lazy.materialize_all()
        rows, cols = sheet.store.used_size()
        for r0 in range(0, rows, 1000):
            for c0 in range(0, cols, 100):
                w = eng.get_cells(h, sheet.id, Window(row0=r0, col0=c0, rows=min(1000, rows - r0), cols=min(100, cols - c0)))
                for c in w.cells:
                    digest.update(f"{sheet.name}|{c.r}|{c.c}|{c.v.model_dump_json() if c.v else ''}|{c.f}|{c.s}\n".encode())
    return digest.hexdigest()


def rows_of(xml: bytes) -> dict[int, bytes]:
    pos = [(int(m.group(1)), m.start()) for m in ROW.finditer(xml)]
    return {r: xml[a : (pos[i + 1][1] if i + 1 < len(pos) else len(xml))] for i, (r, a) in enumerate(pos)}


def edit_and_export(path: Path, out: Path):
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(path)
    rnd = random.Random(hashlib.sha256(path.name.encode()).digest()[0])
    edited_rows: dict[str, set[int]] = {}
    for i, s in enumerate(wb.sheets):
        for _ in range(3):
            r, c = rnd.randrange(max(min(s.row_count, 5000), 1)), rnd.randrange(max(s.col_count, 1))
            value = NumValue(n=1.25) if rnd.random() < 0.5 else StrValue(s="سلام & <x> _x000D_")
            try:
                d = eng.apply_cell_edits(h, s.id, [CellEdit(r=r, c=c, value=value)])
                sheets = eng._open[h.id].sheets
                edited_rows.setdefault(sheets[i].part_name, set()).add(r + 1)
                # recalculated dependents (E7) are part of the delta and legitimately rewrite their rows
                for cell in d.after:
                    edited_rows[sheets[i].part_name].add(cell.r + 1)
                for other in d.others:
                    part = next(x.part_name for x in sheets if x.id == other.sheet_id)
                    edited_rows.setdefault(part, set()).update(cell.r + 1 for cell in other.after)
            except GridoraEngineError as e:
                assert e.reason == "edit.protected_formula_cell"  # the only allowed refusal
    # un-sharing a shared formula group (E7) rewrites every row of the group: those rows are dirty too
    for sh in eng._open[h.id].sheets:
        if sh.dirty:
            edited_rows.setdefault(sh.part_name, set()).update((k >> 14) + 1 for k in sh.dirty)
    report = eng.export_xlsx(h, out)
    return eng, h, edited_rows, report


def check_round_trip(path: Path, tmp_path: Path):
    out = tmp_path / "out.xlsx"
    eng, h, edited_rows, report = edit_and_export(path, out)
    live = fingerprint(eng, h)
    eng2 = create_engine({})
    h2, _wb2, _ = eng2.import_xlsx(out)  # the exported file must open with our own reader
    assert fingerprint(eng2, h2) == live
    a, b = parts_of(path), parts_of(out)
    allowed = set(edited_rows) | {"xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml", "xl/calcChain.xml"}
    changed = {n for n in set(a) | set(b) if a.get(n) != b.get(n)}
    assert changed <= allowed, changed - allowed
    if "xl/workbook.xml" in changed:  # only fullCalcOnLoad may differ
        norm = b["xl/workbook.xml"].replace(b' fullCalcOnLoad="1"', b"").replace(b'<calcPr fullCalcOnLoad="1"/>', b"")
        assert norm == a["xl/workbook.xml"]
    for name in changed - {"xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml", "xl/calcChain.xml"}:
        old, new = rows_of(a[name]), rows_of(b[name])
        touched = {r for r in set(old) | set(new) if old.get(r) != new.get(r)}
        assert touched <= edited_rows[name], f"{name}: rows {sorted(touched - edited_rows[name])[:5]} changed without an edit"
        head_old = a[name][: a[name].index(b"<sheetData")]
        head_new = b[name][: b[name].index(b"<sheetData")]
        assert head_old == head_new or re.sub(rb'(<dimension\b[^>]*?\bref=")[^"]*', rb"\1", head_old) == re.sub(rb'(<dimension\b[^>]*?\bref=")[^"]*', rb"\1", head_new)
    assert not (tmp_path / "out.xlsx.part").exists()
    return report


@pytest.mark.parametrize("rel", POI, ids=[Path(p).name for p in POI])
def test_apache_poi_file_survives_edit_export_reimport(corpus_root, tmp_path, rel):
    check_round_trip(ROOT / rel, tmp_path)


@pytest.mark.parametrize("entry", PRIVATE, ids=[Path(f["path"]).name[:40] for f in PRIVATE])
def test_private_file_survives_edit_export_reimport(corpus_root, tmp_path, entry):
    p = find_private(entry)
    if p is None:
        pytest.skip("private file not present")
    check_round_trip(p, tmp_path)


SOFFICE = shutil.which("soffice")


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) not installed")
@pytest.mark.parametrize("name", ["apache-poi/45544.xlsx", "apache-poi/57181.xlsm", "apache-poi/ExcelPivotTableSample.xlsx",
                                  "apache-poi/Tables.xlsx", "apache-poi/LIBRE_OFFICE-116306-0.xlsx"])
def test_libreoffice_opens_the_exported_file_and_shows_the_edit(corpus_root, tmp_path, name):
    """Secondary oracle: not Excel. The first sheet gets a unique marker text in a fresh cell."""
    marker = "GRIDORA_MARKER_42"
    eng = create_engine({})
    h, wb, _ = eng.import_xlsx(ROOT / name)
    eng.apply_cell_edits(h, wb.sheets[0].id, [CellEdit(r=2, c=14, value=StrValue(s=marker))])
    out = tmp_path / ("o." + Path(name).suffix[1:])
    eng.export_xlsx(h, out)
    subprocess.run([SOFFICE, "--headless", f"-env:UserInstallation=file://{tmp_path}/profile", "--convert-to", "csv",
                    "--outdir", str(tmp_path), str(out)], check=True, capture_output=True, timeout=240)
    csv_text = (tmp_path / "o.csv").read_text(encoding="utf-8", errors="replace")
    assert marker in csv_text
