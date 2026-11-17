"""Package writer: clean parts are streamed from the source archive unchanged."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from ..errors import GridoraEngineError
from .parts import PackageModel, Part

_FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def write_package(model: PackageModel, path: Path) -> None:
    """Write all non-dropped parts of the model in their original order."""
    write_parts(model, model.parts, path)


def write_parts(model: PackageModel | None, parts: list[Part], path: Path) -> None:
    """Write `parts` (copies may carry data/producer/state overrides; the model is not changed).
    Zip container metadata (timestamps, compression level, extra fields) is not preserved; part
    content is. Atomic: written to `<path>.part`, then renamed."""
    tmp = path.with_name(path.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for part in parts:
                if part.state == "dropped":
                    continue
                info = zipfile.ZipInfo(part.name, _FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                with zout.open(info, "w", force_zip64=True) as dst:
                    if part.data is not None:
                        dst.write(part.data)
                    elif part.producer is not None:
                        for chunk in part.producer():
                            dst.write(chunk)
                    else:
                        assert model is not None  # clean parts stream from the source archive
                        for chunk in model.zin.iter_chunks(part.name):
                            dst.write(chunk)
        os.replace(tmp, path)
    except GridoraEngineError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError:
        tmp.unlink(missing_ok=True)
        raise GridoraEngineError(
            "internal_error", "io.write_failed", "The file could not be written."
        ) from None
