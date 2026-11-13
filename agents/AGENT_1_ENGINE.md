# Agent 1 — Workbook Engine & Excel Compatibility

You work in `packages/engine/` only. Read first: `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/COMPATIBILITY_STRATEGY.md`, `docs/SECURITY_MODEL.md`, `docs/MODULE_BOUNDARIES.md`, `contracts/`, `docs/WORKFLOW.md`.

## Mission
Give Gridora a trustworthy workbook layer: open XLSX/CSV, expose cells, apply edits with deltas, recalculate formulas, export, and honestly report what was not understood.

## Step 0 — Plan first (no code yet)
Submit `packages/engine/PLAN.md` as a PR containing: module layout, how the OOXML package layer preserves unknown parts, formula strategy, test plan, risks. Wait for Agent 0 approval.

## Step 1 — Engine spike (time-boxed, written report)
Evaluate IronCalc, GridCraft, Gridline and at least one more candidate (e.g. a Python OOXML library such as openpyxl for parsing only). For each: verify the license in the repo (not the README), commit hash, dependencies, tests, build time, binding options (PyO3 / subprocess), XLSX round-trip on our fixtures, formula coverage, 100k-row performance, security notes. Output `packages/engine/SPIKE_REPORT.md` with a recommendation and what could be reused. Do not copy code before the report and a `THIRD_PARTY_NOTICES.md` entry exist. Agent 0 decides (ADR-003).

## Deliverables
1. `WorkbookEngine` implementation (see `contracts/python/gridora_contracts/protocols.py`).
2. OOXML package layer: unknown parts, relationships and content types preserved byte-for-byte; only dirty parts regenerated.
3. Compatibility feature registry with stable codes and fixtures; the import/export `CompatibilityReport` generated from it.
4. CSV import/export including UTF-8 (with/without BOM) and Windows-1256 detection, and Persian digits in values.
5. RTL sheet view flag (`SheetMeta.rtl`) read from and written to XLSX.
6. Formula evaluation for a documented function subset; unsupported functions keep cached values and are reported.
7. Fixture corpus under `packages/engine/tests/fixtures/` with a README stating where each file came from.
8. Benchmark script for 100k rows × 20 columns (open, get_cells window, edit, export), results in `BENCHMARKS.md`.

## Acceptance criteria
- Import → edit → export → re-import preserves cells, formulas, styles for supported features; unknown parts byte-equal.
- Every unsupported or lossy item appears in the report; nothing silently dropped.
- Hostile inputs rejected safely: zip bomb, XXE/DTD, path traversal entries, absurd sheet dimensions, corrupted parts, time/memory limits.
- No filesystem paths leak in errors; typed exceptions with stable codes from `ERROR_CODES`.
- Never claims "full Excel compatibility".
- Does not import `packages/dataops` or `apps/*`.

## Must not modify
`contracts/`, `apps/`, `packages/dataops/`, `docs/` (except your own module docs under `packages/engine/`).
