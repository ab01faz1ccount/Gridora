# packages/engine — workbook engine

The in-memory spreadsheet model: CSV and XLSX import (lazy, hostile-safe), cell edits with exact undo/redo deltas, formulas (about 400 functions, dynamic arrays, Jalali/Gregorian/Hijri calendar modes), XLSX/CSV export that preserves what it does not edit, and a compatibility report for everything it cannot represent. Entry point: `gridora_engine.create_engine(config)`.

Full description of what it does, how it is built and its limits: [docs/REFERENCE.md](../../docs/REFERENCE.md#workbook-engine-packagesengine). Design record: [DESIGN.md](DESIGN.md)

```bash
pip install -e ../../contracts/python -e '.[dev]'
pytest -q && ruff check . && mypy src
```
