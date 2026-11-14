from __future__ import annotations

import uuid
from pathlib import Path

from gridora_contracts.protocols import CsvOptions

from ..compat.report import build_report
from ..errors import file_too_large, import_failed
from ..limits import Deadline, ResourceLimits
from ..model.sheet import SheetStore, StoreBudget
from ..model.workbook import SheetState, WorkbookState
from .detect import check_delimiter, decode, detect_delimiter
from .reader import load_into


def import_csv_file(
    path: Path, options: CsvOptions, limits: ResourceLimits, file_id: str | None
) -> WorkbookState:
    deadline = Deadline(limits.deadline_seconds)
    try:
        with open(path, "rb") as f:
            data = f.read(limits.max_file_bytes + 1)
    except OSError:
        raise import_failed("io.read_failed", "The file could not be read.") from None
    if len(data) > limits.max_file_bytes:
        raise file_too_large("limits.file_too_large", "The file is larger than allowed.")

    text, _encoding, guessed = decode(data, options.encoding)
    del data
    detected = options.delimiter is None
    delimiter = detect_delimiter(text) if detected else check_delimiter(options.delimiter or "")

    budget = StoreBudget(limits.max_store_bytes, limits.max_cells)
    state = WorkbookState(
        id=str(uuid.uuid4()), file_id=file_id or "", name=path.stem, budget=budget
    )
    store = SheetStore(budget)
    stats = load_into(store, state.strings, text, delimiter, options.infer_types, limits, deadline)
    state.sheets.append(SheetState(id=str(uuid.uuid4()), name="Sheet1", index=0, store=store))
    state.compat = build_report(
        "import",
        {
            "csv.encoding_guessed": int(guessed),
            "csv.delimiter_detected": int(detected),
            "csv.persian_digits_normalized": stats.persian_normalized,
            "csv.numeric_like_kept_as_text": stats.kept_as_text,
        },
    )
    return state
