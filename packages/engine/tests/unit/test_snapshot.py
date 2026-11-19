from __future__ import annotations

import hashlib
import zlib

import pytest
from gridora_contracts.models import (
    CellEdit,
    CellPatchDelta,
    ColumnarColumn,
    ColumnarRange,
    NumValue,
    Range,
    RangeSnapshotDelta,
)
from support import make_xlsx, read_parts, read_window, sheet_doc

from gridora_engine import create_engine
from gridora_engine.csvio.options import CsvImportOptions
from gridora_engine.errors import GridoraEngineError
from gridora_engine.limits import ResourceLimits
from gridora_engine.model.snapshot import _HEADER, decode_range, encode_range


class Blobs:
    """A fake BlobStore (contract 0.4.1): content-addressed refs."""

    def __init__(self):
        self.data: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        ref = hashlib.sha256(data).hexdigest()[:16]
        self.data[ref] = data
        return ref

    def get(self, ref: str) -> bytes:
        return self.data[ref]


def csv_wb(tmp_path, text, blobs=None, **cfg):
    eng = create_engine(cfg, blobs)
    p = tmp_path / "t.csv"
    p.write_text(text, encoding="utf-8")
    h, wb = eng.import_csv(p, CsvImportOptions())
    return eng, h, wb.sheets[0]


def rng_of(s, r0, c0, r1, c1):
    return Range(sheet_id=s.id, r0=r0, c0=c0, r1=r1, c1=c1)


def data_of(rng, *cols):
    return ColumnarRange(range=rng, columns=[ColumnarColumn(kind=k, values=v) for k, v in cols])


def fp(eng, h, s):
    return {k: (c.v.model_dump_json() if c.v else None, c.f, c.s) for k, c in read_window(eng, h, s).items()}


def big_write(eng, h, s, rows=40, cols=3, offset=0):
    rng = rng_of(s, 0, 0, rows - 1, cols - 1)
    return eng.write_range_columnar(h, rng, data_of(rng, *[("num", [float(offset + r * (c + 1)) for r in range(rows)]) for c in range(cols)]))


TEXT = "a,b,c\n" + "".join(f"{i},w{i},{i * 2}\n" for i in range(60))


def test_small_writes_stay_cell_patches_and_large_ones_become_snapshots(tmp_path):
    blobs = Blobs()
    eng, h, s = csv_wb(tmp_path, TEXT, blobs, limits={"max_patch_cells": 20})
    rng = rng_of(s, 0, 0, 2, 2)
    small = eng.write_range_columnar(h, rng, data_of(rng, ("num", [1.0, 2.0, 3.0]), ("num", [1.0, 2.0, 3.0]), ("num", [1.0, 2.0, 3.0])))
    assert isinstance(small, CellPatchDelta) and not blobs.data
    big = big_write(eng, h, s)  # 120 cells, cap 20
    assert isinstance(big, RangeSnapshotDelta) and big.range == rng_of(s, 0, 0, 39, 2)
    assert big.cell_count == 120 - 0 or big.cell_count <= 120
    assert big.before_ref in blobs.data and big.after_ref in blobs.data and big.before_ref != big.after_ref
    assert eng.read_range_columnar(h, big.range).columns[1].values[5] == 10.0


def test_snapshot_without_a_blob_store_is_too_large_for_history(tmp_path):
    eng, h, s = csv_wb(tmp_path, TEXT, None, limits={"max_patch_cells": 20})
    before = fp(eng, h, s)
    with pytest.raises(GridoraEngineError) as e:
        big_write(eng, h, s)
    assert (e.value.code, e.value.reason) == ("operation_conflict", "too_large_for_history")
    assert fp(eng, h, s) == before


def test_undo_redo_restore_values_strings_styles_and_formulas_exactly(tmp_path):
    rows = ('<row r="1"><c r="A1" s="1"><v>45292</v></c><c r="B1" t="inlineStr"><is><t>سلام</t></is></c><c r="C1"><f>A1*2</f><v>5</v></c></row>'
            '<row r="2"><c r="A2" t="b"><v>1</v></c><c r="B2" t="e"><v>#N/A</v></c><c r="C2"><f>1+1</f></c></row>')
    blobs = Blobs()
    eng = create_engine({"limits": {"max_patch_cells": 2}}, blobs)
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(rows)))
    s = wb.sheets[0]
    original = fp(eng, h, s)
    rng = rng_of(s, 0, 0, 1, 2)
    d = eng.write_range_columnar(h, rng, data_of(rng, ("num", [1.5, 2.5]), ("str", ["x", "y"]), ("num", [None, 9.0])))
    assert isinstance(d, RangeSnapshotDelta)
    after = fp(eng, h, s)
    assert (0, 2) not in after and after[1, 2] == ('{"k":"num","n":9.0}', None, None)  # formulas replaced by a cleared cell and a value
    eng.apply_delta(h, d, inverse=True)
    assert fp(eng, h, s) == original  # including the formulas, the date style and the error cell
    assert fp(eng, h, s)[0, 2][1] == "=A1*2" and fp(eng, h, s)[1, 2][1] == "=1+1" and fp(eng, h, s)[1, 2][0] is None
    eng.apply_delta(h, d, inverse=False)
    assert fp(eng, h, s) == after


def test_blobs_are_deterministic_and_round_trip_through_the_codec(tmp_path):
    eng, h, s = csv_wb(tmp_path, TEXT)
    st = eng._open[h.id]
    a = encode_range(st, st.sheets[0], 0, 0, 30, 2)
    b = encode_range(st, st.sheets[0], 0, 0, 30, 2)
    assert a == b  # identical content -> identical bytes
    dec = decode_range(a, ResourceLimits(), 31, 3)
    assert dec.rows == 31 and dec.cols == 3 and dec.strings[0] == "a" and "w7" in dec.strings
    eng.apply_cell_edits(h, s.id, [CellEdit(r=5, c=0, value=NumValue(n=-1.0))])
    assert encode_range(st, st.sheets[0], 0, 0, 30, 2) != a
    assert len(a) < 31 * 3 * 11  # compressed: smaller than the raw columns


def test_corrupt_unavailable_and_newer_blobs_fail_with_typed_errors_and_change_nothing(tmp_path):
    blobs = Blobs()
    eng, h, s = csv_wb(tmp_path, TEXT, blobs, limits={"max_patch_cells": 20})
    d = big_write(eng, h, s)
    state_after = fp(eng, h, s)
    good = blobs.data[d.before_ref]

    def fails(blob: bytes | None, reason: str):
        if blob is None:
            del blobs.data[d.before_ref]
        else:
            blobs.data[d.before_ref] = blob
        with pytest.raises(GridoraEngineError) as e:
            eng.apply_delta(h, d, inverse=True)
        assert e.value.code == "internal_error" and e.value.reason == reason
        assert fp(eng, h, s) == state_after  # undo never half-applies
        blobs.data[d.before_ref] = good

    fails(None, "snapshot.unavailable")
    fails(good[: len(good) // 2], "snapshot.corrupt")  # truncated
    fails(b"junk" + good[4:], "snapshot.corrupt")  # wrong magic
    flipped = bytearray(good)
    flipped[-5] ^= 0xFF
    fails(bytes(flipped), "snapshot.corrupt")  # damaged compressed body
    hdr = list(_HEADER.unpack_from(good))
    body = zlib.decompress(good[_HEADER.size :])
    hdr[4] = 99  # wrong claimed row count
    fails(_HEADER.pack(*hdr) + good[_HEADER.size :], "snapshot.corrupt")
    hdr = list(_HEADER.unpack_from(good))
    hdr[1] = 2  # newer format version
    fails(_HEADER.pack(*hdr) + good[_HEADER.size :], "snapshot.unsupported_version")
    hdr = list(_HEADER.unpack_from(good))
    hdr[6] = hashlib.sha256(b"x").digest()  # checksum mismatch
    fails(_HEADER.pack(*hdr) + good[_HEADER.size :], "snapshot.corrupt")
    tampered = bytearray(body)
    tampered[0] = 99  # a tag byte outside the known range, with a matching checksum
    hdr = list(_HEADER.unpack_from(good))
    hdr[6] = hashlib.sha256(bytes(tampered)).digest()
    fails(_HEADER.pack(*hdr) + zlib.compress(bytes(tampered)), "snapshot.corrupt")
    eng.apply_delta(h, d, inverse=True)  # and the intact blob still works


def test_decompression_bombs_and_oversized_claims_are_refused(tmp_path):
    lim = ResourceLimits()
    body = b"\x00" * (50 << 20)
    bomb = _HEADER.pack(b"GRSB", 1, 0, 2, 2, 44, hashlib.sha256(body).digest()) + zlib.compress(body)  # claims 44 bytes, expands to 50 MB
    with pytest.raises(GridoraEngineError) as e:
        decode_range(bomb, lim, 2, 2)
    assert e.value.reason == "snapshot.corrupt"
    huge = _HEADER.pack(b"GRSB", 1, 0, 10**6, 10**6, 1, b"\0" * 32) + b""
    with pytest.raises(GridoraEngineError):
        decode_range(huge, lim, 10**6, 10**6)
    with pytest.raises(GridoraEngineError):
        decode_range(b"", lim, 1, 1)


def test_missing_store_failures_become_typed_errors(tmp_path):
    class Broken:
        def put(self, data):
            raise OSError("disk full: /secret/path")

        def get(self, ref):
            raise OSError("nope")

    eng, h, s = csv_wb(tmp_path, TEXT, Broken(), limits={"max_patch_cells": 20})
    before = fp(eng, h, s)
    with pytest.raises(GridoraEngineError) as e:
        big_write(eng, h, s)
    assert e.value.reason == "snapshot.store_failed" and "secret" not in str(e.value)
    assert fp(eng, h, s) == before
    eng2, h2, s2 = csv_wb(tmp_path, TEXT, None)
    fake = RangeSnapshotDelta(sheet_id=s2.id, range=rng_of(s2, 0, 0, 1, 1), before_ref="a", after_ref="b", cell_count=4)
    with pytest.raises(GridoraEngineError) as e2:
        eng2.apply_delta(h2, fake, inverse=False)
    assert e2.value.reason == "snapshot.unavailable"


def test_snapshots_over_a_lazy_xlsx_sheet_and_budget_atomicity(tmp_path):
    body = "".join(f'<row r="{r}"><c r="A{r}"><v>{r}</v></c><c r="B{r}" t="inlineStr"><is><t>t{r}</t></is></c></row>' for r in range(1, 700))
    blobs = Blobs()
    eng = create_engine({"limits": {"max_patch_cells": 50}}, blobs)
    h, wb, _ = eng.import_xlsx(make_xlsx(tmp_path / "x.xlsx", sheet_doc(body)))
    s = wb.sheets[0]
    original = fp(eng, h, s)
    rng = rng_of(s, 100, 0, 599, 1)  # 1000 cells in blocks that were never parsed
    d = eng.write_range_columnar(h, rng, data_of(rng, ("num", [float(i) for i in range(500)]), ("str", [f"n{i}" for i in range(500)])))
    assert isinstance(d, RangeSnapshotDelta)
    eng.apply_delta(h, d, inverse=True)
    assert fp(eng, h, s) == original
    small = create_engine({"limits": {"max_patch_cells": 50, "max_cells": 1500}}, blobs)  # room for the sheet (1,398 cells), not for +1,800 more
    h2, wb2, _ = small.import_xlsx(make_xlsx(tmp_path / "y.xlsx", sheet_doc(body)))
    s2 = wb2.sheets[0]
    before = fp(small, h2, s2)
    wide = rng_of(s2, 0, 2, 599, 3)  # 1,200 cells: within the range cap, but 2,598 cells in total
    with pytest.raises(GridoraEngineError) as e:
        small.write_range_columnar(h2, wide, data_of(wide, *[("num", [1.0] * 600)] * 2))
    assert e.value.reason == "limits.cell_count_exceeded" and fp(small, h2, s2) == before


def test_export_regenerates_bulk_written_rectangles_and_nothing_else(tmp_path):
    body = "".join(f'<row r="{r}" ht="18" customHeight="1"><c r="A{r}"><v>{r}</v></c><c r="B{r}" t="inlineStr"><is><t>t{r}</t></is></c>'
                   f'<c r="D{r}"><v>{r * 3}</v></c></row>' for r in range(1, 400))
    blobs = Blobs()
    eng = create_engine({"limits": {"max_patch_cells": 50}}, blobs)
    src = make_xlsx(tmp_path / "x.xlsx", sheet_doc(body))
    h, wb, _ = eng.import_xlsx(src)
    s = wb.sheets[0]
    rng = rng_of(s, 10, 0, 109, 1)  # A11:B110, column D untouched
    d = eng.write_range_columnar(h, rng, data_of(rng, ("num", [float(-i) for i in range(100)]), ("str", [f"é{i}" for i in range(100)])))
    assert isinstance(d, RangeSnapshotDelta)
    out = tmp_path / "o.xlsx"
    rep = eng.export_xlsx(h, out)
    eng2 = create_engine({})
    h2, wb2, _ = eng2.import_xlsx(out)
    assert fp(eng2, h2, wb2.sheets[0]) == fp(eng, h, s)
    a, b = read_parts(src)["xl/worksheets/sheet1.xml"], read_parts(out)["xl/worksheets/sheet1.xml"]
    old, new = a.split(b"</row>"), b.split(b"</row>")
    changed = [i for i, (x, y) in enumerate(zip(old, new, strict=True)) if x != y]
    assert changed == list(range(10, 110))  # only the 100 rows of the rectangle differ
    assert b'ht="18"' in new[50] and b"<v>153</v>" in new[50]  # row attributes and the untouched cell D survive
    assert "xlsx.inline_strings" in {i.code for i in rep.items}
