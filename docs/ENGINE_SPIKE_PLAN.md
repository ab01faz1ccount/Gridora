# Gridora — Engine Spike Plan (feeds ADR-003)

Purpose: decide, with evidence, how Gridora gets XLSX fidelity and formula evaluation. Owner: Agent 1. Decision: Agent 0.

## Candidates
IronCalc · GridCraft · Gridline · at least one non-Rust option (e.g. openpyxl/pyxlsb-style parsing for read, a Python or Rust formula evaluator) · "build our own" baseline.

## Evaluation matrix (each cell needs evidence, not README claims)
| Criterion | How to verify |
|---|---|
| License and redistribution | Read the LICENSE files in the repo and every vendored/bundled asset; record commit hash |
| Maturity | Commit history, issues, release cadence, test suite size and pass rate |
| Dependencies | `cargo tree` / lockfile review; license of each |
| Build effort | Clean build time and toolchain requirements (e.g. Rust version) |
| Integration | PyO3/maturin, subprocess JSON-RPC, or port-by-idea; effort estimate |
| XLSX round-trip | Run the fixture corpus; diff parts; count lost features |
| Unknown-part preservation | Does it keep parts it doesn't understand? Test with a pivot, chart, VBA and custom XML file |
| Formulas | Run a function-coverage test sheet; compare with LibreOffice results |
| Performance | 100k×20 open, window read, edit, recalc, save; memory |
| Security | Fuzz/hostile inputs: zip bomb, XXE, traversal; unsafe code; network or file functions |
| Extractability | Can a single algorithm or module be reused under its license? |

## Fixtures
Small per-feature files, a Persian sheet-name/RTL file, a 100k-row file, a pivot/chart/VBA file, and the hostile set. Provenance recorded in `packages/engine/tests/fixtures/README.md`.

## Decision options
A. Own OOXML layer + bind a Rust core (PyO3/maturin).
B. Own OOXML layer + Rust core as a subprocess (JSON-RPC).
C. Own OOXML layer + pure-Python formula evaluator.
D. Wrap a single external library (rejected by default: violates the no-single-dependency rule unless evidence is overwhelming).

## Timebox and output
Fixed timebox set in the Agent 1 plan approval. Output `packages/engine/SPIKE_REPORT.md` with the filled matrix, a recommendation, risks, and a provenance list. Agent 0 records the outcome in ADR-003.
