# E7 formula core — evidence for ADR-003 part 2 (2026-11-20)

Evidence behind the formula-core decision (ADR-003 part 2, ADR-016); the staged pure-Python evaluator it recommended is implemented. Script: `packages/engine/benchmarks/formula_inventory.py` (raw XML scan of `<f>` elements; counts function-call tokens, so nested/rare syntax may be under- or over-counted).

## Gate from ADR-015 (item 5)
- E6 (export) merged: yes (engine README, E5b-2).
- Owner real files measured: yes, see `packages/engine/BENCHMARKS.md` "Corpus". All are small (largest 189 KB); full parse is milliseconds.
- **Not met by evidence:** "a real 100k x 20 file". None exists in the corpus, so the 30 s Rust trigger is untested, not passed. The synthetic 100k x 20 full parse remains 11-13 s.

## What the owner's real workbook uses
`softwiro-piece-rate-payroll` (6,806 formulas, 7 RTL sheets) uses only 8 functions:
IF 8,901 · IFERROR 3,000 · INDEX 3,000 · MATCH 3,000 · OR 3,000 · DATE 800 · SUMIFS 400 · SUM 4.
`file_example_XLSX_5000` and `Product-Sales-Region` contain no formulas.

Across the Apache POI corpus the dominant ones are IF, ROW, INDIRECT, VLOOKUP, OR, MATCH, IFERROR, INDEX, ISNA, DATE, SUMIFS, then TEXT, SUM, SUBTOTAL, math/trig and text functions (POI's own `FormulaEvalTestData*.xlsx` is the broad-coverage test).

## Recommendation (the maintainer, for decision)
Option **C, staged**: own pure-Python evaluator behind the existing engine interface, no Rust.
1. Tier 1 (covers the owner's workbook): parser for A1 refs/ranges/cross-sheet refs, operators, IF/IFERROR/IFNA/AND/OR/NOT, INDEX/MATCH/VLOOKUP, SUM/SUMIFS/COUNTIFS/AVERAGE/MIN/MAX/COUNT, DATE/TODAY-free date functions, ROUND/ABS.
2. Dependency graph with dirty propagation, populating `Delta` dependents (CC-4). Unsupported function -> keep cached value, mark cell in the CompatibilityReport (never silently wrong).
3. Tier 2 from the POI inventory, driven by `FormulaEvalTestData*.xlsx` as oracle (cached values written by Excel).
4. Bring Rust back only if (a) a real 100k-row formula workbook recalculates slower than the agreed budget, or (b) tier 2 stalls.

Why not A/B now: the Rust toolchain/IronCalc source build is unverified (spike items open), and the real workload is 8 functions on thousands of cells, well inside pure Python.

Risks: volatile functions (INDIRECT, ROW with refs), full-column references (`VLookupFullColumn.xlsx`), shared-formula translation, Excel's number/text coercion rules, Persian digit handling inside text functions.

## Decision needed
Owner: accept C-staged (yes/no). If yes, E7 tier 1 starts; first PR is the parser + evaluator for the 8 owner functions with tests against the cached values in `softwiro` (6,806 formulas as oracle).
