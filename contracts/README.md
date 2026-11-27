# contracts/

Normative shared types and module interfaces. Every module imports from here; nothing else defines what travels between the engine, dataops, the API and the web app. Current version: see `CONTRACT_VERSION` in `python/gridora_contracts/models.py`.

- `python/gridora_contracts/models.py` — pydantic v2 data models (mirrors `docs/DATA_MODEL.md`).
- `python/gridora_contracts/protocols.py` — `WorkbookEngine` and its optional extensions, `OperationExecutor`, `TableStore`, `ExecContext`, `BlobStore`.
- `typescript/index.ts` — the same types for the web app.
- `python/tests/` — contract tests; keep green.

Rules: the Python and TypeScript files stay in sync; a change touches both, plus `docs/DATA_MODEL.md` and `docs/API_CONTRACTS.md` when a shape changes. Changes are additive within a minor version (new optional fields and protocols); a removal or rename is a major change and needs an ADR in `docs/DECISIONS.md`. Error codes are added, never renamed.

Install for local development: `pip install -e contracts/python`. Run tests: `pytest contracts/python/tests`.

## Changelog
- **0.2.0** — first Phase 2 set (ADR-010): `file_id` on imports, `close`, optional `FormattingEngine` / `StructureEngine`, `extra_targets`, `CellsChangedResult`, window cap 1000 x 100.
- **0.3.0** — `export_csv` returns a `CompatibilityReport`.
- **0.4.0** — `DataTableTarget.version`; optional `ColumnarExecContext`; `RangeSnapshotDelta` and `BlobStore`.
- **0.4.1** — optional `ColumnarEngine`; history size limit reported as `operation_conflict` with detail `too_large_for_history`.
- **0.5.0** — `others` on `CellPatchDelta` / `CellsChangedResult` (edits that change other sheets).
- **0.6.x+** — `gridora_contracts.persian`: the single Persian/Arabic text fold shared by engine and dataops (no schema change).
- **0.6.x** — calendars (`Workbook.calendar`, `DateColumns`, optional `CalendarEngine`), saved tools, charts, Data Table history (see `docs/API_CONTRACTS.md` and ADR-016).
- **0.7.0** — multi-input pipeline steps: `PipelineStep.extra_targets` / `extra_target_inputs`, `ToolInput.kind = "table"`, and `OperationDescriptor.extra_inputs` / `creates_table` / `sheet_output` (additive; lets `join` run inside pipelines and saved tools).
