"""Secondary oracle: LibreOffice must open our no-op round-trip output and see the same data.
LibreOffice is not Excel; this does not prove Excel opens the file (no Excel is available).
Skipped, never silently passed, when soffice is not installed."""
from __future__ import annotations

import shutil
import subprocess

import pytest
from support import write_zip, xlsx_parts

from gridora_engine.limits import ResourceLimits
from gridora_engine.package.parts import PackageModel
from gridora_engine.package.zipout import write_package

SOFFICE = shutil.which("soffice")
pytestmark = pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) not installed")


def to_csv(src, outdir):
    subprocess.run(
        [SOFFICE, "--headless", f"-env:UserInstallation=file://{outdir}/profile", "--convert-to", "csv",
         "--outdir", str(outdir), str(src)],
        check=True, capture_output=True, timeout=180,
    )
    return (outdir / (src.stem + ".csv")).read_text(encoding="utf-8")


@pytest.mark.parametrize("extras", [False, True])
def test_libreoffice_reads_roundtrip_output_like_the_original(tmp_path, extras):
    src = write_zip(tmp_path / "orig.xlsx", xlsx_parts(extras))
    out = tmp_path / "rt.xlsx"
    with PackageModel.open(src, ResourceLimits()) as m:
        write_package(m, out)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    assert to_csv(src, a) == to_csv(out, b)
    assert "علی" in to_csv(out, b)
