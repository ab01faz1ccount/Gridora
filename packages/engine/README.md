# packages/engine — Workbook Engine & Excel Compatibility

Owner: Agent 1. Brief: [agents/AGENT_1_ENGINE.md](../../agents/AGENT_1_ENGINE.md). Plan: [PLAN.md](PLAN.md).

**Status (E0): package skeleton only.** Entry point: `gridora_engine.create_engine(config)`.

What works:
- `create_engine`, handle registry, `close`, typed errors (`errors.py`), resource limits (`limits.py`).
- Conformance with `WorkbookEngine` (contracts v0.2.0), checked by tests.

What does not work yet (every other contract method raises `EngineNotImplementedError`):
`import_xlsx`, `import_csv`, `get_cells`, `apply_cell_edits`, `apply_delta`, `recalculate`,
`export_xlsx`, `export_csv`. `FormattingEngine` and `StructureEngine` are not implemented.

Known limitations:
- Handles are not thread-safe; `apps/api` must serialize access per workbook.
- Time limits are cooperative only; hard memory/time isolation is Phase 4 (ADR-011).

Dev: `pip install -e contracts/python -e "packages/engine[dev]"`, then `ruff check`, `mypy src`, `pytest`.
Proposed CI: `ci/engine.yml.proposed`.
