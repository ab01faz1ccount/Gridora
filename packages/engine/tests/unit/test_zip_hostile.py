from __future__ import annotations

import struct
import zipfile
from dataclasses import replace

import pytest
from support import central_offset, patch, write_zip, xlsx_parts

from gridora_engine.errors import GridoraEngineError
from gridora_engine.limits import ResourceLimits
from gridora_engine.package.zipin import SafeZip

LIM = ResourceLimits()


def open_zip(path, limits=LIM):
    return SafeZip(path, limits)


def reason_of(path, limits=LIM, read_all=False):
    with pytest.raises(GridoraEngineError) as e, open_zip(path, limits) as z:
        if read_all:
            for n in z.names():
                z.read(n)
    err = e.value
    # never leak the temp directory or the file name
    assert str(path.parent) not in str(err) and path.name not in str(err)
    return err.reason


def small(tmp_path, parts=None, **kw):
    return write_zip(tmp_path / "t.xlsx", parts or {"a.xml": "<a/>", "b.xml": "<b/>"}, **kw)


def test_valid_package_opens_and_reads(tmp_path):
    p = write_zip(tmp_path / "ok.xlsx", xlsx_parts())
    with open_zip(p) as z:
        assert z.names()[0] == "[Content_Types].xml" and b"<sst" in z.read("xl/sharedStrings.xml")


@pytest.mark.parametrize(
    "data,reason",
    [(b"", "zip.not_a_zip"), (b"hello world", "zip.not_a_zip"),
     (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 100, "xlsx.encrypted_or_legacy"),
     (b"PK\x03\x04" + b"x" * 100, "zip.corrupt")],
)
def test_not_a_package(tmp_path, data, reason):
    p = tmp_path / "x.xlsx"
    p.write_bytes(data)
    assert reason_of(p) == reason


def test_truncated_zip(tmp_path):
    raw = small(tmp_path).read_bytes()
    p = tmp_path / "cut.xlsx"
    p.write_bytes(raw[: len(raw) // 2])
    assert reason_of(p) == "zip.corrupt"


def test_file_too_large(tmp_path):
    with pytest.raises(GridoraEngineError) as e:
        open_zip(small(tmp_path), replace(LIM, max_file_bytes=10))
    assert e.value.code == "file_too_large"


def test_entry_count_cap_applies_before_any_table_is_built(tmp_path):
    p = write_zip(tmp_path / "many.xlsx", {f"f{i}.xml": "<a/>" for i in range(5)})
    assert reason_of(p, replace(LIM, max_zip_entries=3)) == "zip.too_many_entries"


@pytest.mark.parametrize(
    "name",
    ["../evil.xml", "a/../../evil.xml", "/abs/evil.xml", "a\\b.xml", "C:/evil.xml", "a//b.xml",
     "./a.xml", "a/./b.xml", "bad\x01name.xml", "x" * 600],
)
def test_unsafe_names_rejected(tmp_path, name):
    p = write_zip(tmp_path / "n.xlsx", {"ok.xml": "<a/>", name: "<a/>"})
    assert reason_of(p) == "zip.path_traversal"


def test_nul_in_name_rejected(tmp_path):
    p = small(tmp_path, {"ok.xml": "<a/>", "evilXname.xml": "<a/>"})
    raw = p.read_bytes().replace(b"evilXname", b"evil\x00name")
    p.write_bytes(raw)
    assert reason_of(p) == "zip.path_traversal"


def _append_duplicate(p):
    with zipfile.ZipFile(p, "a") as z:
        z.writestr("a.xml", "<b/>")


def test_duplicate_and_case_folded_duplicate_names(tmp_path):
    p = write_zip(tmp_path / "d.xlsx", {"a.xml": "<a/>"})
    with pytest.warns(UserWarning):
        _append_duplicate(p)
    assert reason_of(p) == "zip.duplicate_name"
    p2 = write_zip(tmp_path / "d2.xlsx", {"A.xml": "<a/>", "a.XML": "<b/>"})
    assert reason_of(p2) == "zip.duplicate_name"


def test_encrypted_entry_flag(tmp_path):
    p = small(tmp_path)
    raw = p.read_bytes()
    raw = patch(raw, central_offset(raw, "a.xml") + 8, "<H", 1)
    p.write_bytes(raw)
    assert reason_of(p) == "zip.encrypted"


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_unsupported_compression_method(tmp_path, method):
    assert reason_of(small(tmp_path, method=method)) == "zip.method_unsupported"


def test_ratio_bomb_rejected_before_decompression(tmp_path):
    p = write_zip(tmp_path / "b.xlsx", {"big.xml": b"\x00" * (5 << 20)})
    assert p.stat().st_size < 20_000
    assert reason_of(p, replace(LIM, max_uncompressed_bytes=50 << 20)) == "zip.ratio_exceeded"


def test_total_and_part_budgets(tmp_path):
    p = write_zip(tmp_path / "t.xlsx", {"a.xml": b"ab" * (1 << 19), "b.xml": b"cd" * (1 << 19)})
    assert reason_of(p, replace(LIM, max_uncompressed_bytes=1_500_000, max_compression_ratio=10**6)) == "zip.uncompressed_too_large"
    assert reason_of(p, replace(LIM, max_part_bytes=500_000, max_compression_ratio=10**6)) == "zip.part_too_large"


def test_runtime_budget_counts_bytes_actually_produced(tmp_path):
    parts = {"a.xml": b"x" * 600_000, "b.xml": b"y" * 600_000}
    p = write_zip(tmp_path / "t.xlsx", parts, stored={"a.xml", "b.xml"})
    # declared total (1.2 MB) fits the limit; reading both would exceed a lowered live budget
    with open_zip(p, replace(LIM, max_uncompressed_bytes=1_250_000)) as z:
        z.read("a.xml")
        z.total_read = 1_000_000  # simulate earlier reads using up the budget
        with pytest.raises(GridoraEngineError) as e:
            z.read("b.xml")
        assert e.value.reason == "zip.uncompressed_too_large"


def test_lying_declared_size_is_not_trusted(tmp_path):
    p = write_zip(tmp_path / "l.xlsx", {"a.xml": b"z" * 5000, "b.xml": "<b/>"}, stored={"a.xml"})
    raw = p.read_bytes()
    raw = patch(raw, central_offset(raw, "a.xml") + 24, "<I", 10)
    p.write_bytes(raw)
    assert reason_of(p, read_all=True) in {"zip.size_mismatch", "zip.bad_crc", "zip.corrupt"}


def test_bad_crc_detected(tmp_path):
    p = write_zip(tmp_path / "c.xlsx", {"a.xml": b"hello world " * 50}, stored={"a.xml"})
    raw = bytearray(p.read_bytes())
    i = raw.index(b"hello world")
    raw[i] ^= 0xFF
    p.write_bytes(bytes(raw))
    assert reason_of(p, read_all=True) == "zip.bad_crc"


def test_overlapping_entries_rejected(tmp_path):
    p = small(tmp_path)
    raw = p.read_bytes()
    off_a = struct.unpack_from("<I", raw, central_offset(raw, "a.xml") + 42)[0]
    raw = patch(raw, central_offset(raw, "b.xml") + 42, "<I", off_a)
    p.write_bytes(raw)
    assert reason_of(p) == "zip.overlapping_entries"


def test_local_header_name_must_match_central_directory(tmp_path):
    p = small(tmp_path, {"a.xml": "<a/>", "bbbb.xml": "<b/>"})
    p.write_bytes(p.read_bytes().replace(b"PK\x03\x04", b"PK\x03\x04", 2))
    raw = bytearray(p.read_bytes())
    i = raw.index(b"PK\x03\x04", 4)  # second local header
    j = raw.index(b"bbbb.xml", i)
    raw[j: j + 4] = b"cccc"
    p.write_bytes(bytes(raw))
    assert reason_of(p) == "zip.local_header_mismatch"


def test_directory_entries_are_ignored_not_parts(tmp_path):
    p = write_zip(tmp_path / "dir.xlsx", {"xl/": b"", "xl/a.xml": "<a/>"})
    with open_zip(p) as z:
        assert z.names() == ["xl/a.xml"]
