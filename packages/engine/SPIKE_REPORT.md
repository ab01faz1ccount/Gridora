# Engine spike report (E2) — input to ADR-003

Owner: Agent 1. Decision: Agent 0. Status: **partial, honest.** Done: license audits of all five
named candidates plus two Python formula libraries, hands-on tests of IronCalc and openpyxl, security
probes, performance probes. **Not done:** any hands-on test of GridCraft (no Rust toolchain in my
environment), IronCalc built from source, real Excel-produced fixtures (none available to me).
Scripts: `spike/` (my code only). All timings: 1-CPU Linux container, Python 3.12.3, single runs.

## 1. Recommendation

1. **Own the OOXML package layer. Confirmed necessary.** Neither tested library keeps unknown parts,
   and IronCalc also drops Persian-critical details (below). This is needed under every option.
2. **Formula core: leaning Option A (bind IronCalc via PyO3), not yet decided.** The evidence is
   strong on speed and on correctness of a 107-formula sample; it is weak on exactly what I could not
   test (building from source, real Excel files, spill behavior, a recalculation API that does not
   re-evaluate the whole workbook). Option C (own pure-Python evaluator) stays the fallback and the
   test reference.
3. **Nothing in E3–E6 depends on this decision.** The package layer, store, CSV and deltas are the
   same under A, B and C. The decision is needed at **E7**. The `FormulaBackend` interface in
   PLAN.md section 8 keeps both open. I will not start E7 before ADR-003 is decided.
4. **Open items before ADR-003 can close** (each is small): build IronCalc from source in our
   toolchain (needs Rust in CI/Docker and a decision on pinning: I only tested the PyPI wheel);
   test its `UserModel` change diffs for "which dependents changed" (CC-4 needs them); test spill
   (`UNIQUE`, `SEQUENCE` returned only the first element through `get_cell_value`); run the formula
   comparison on Excel-produced files supplied by the owner.

## 2. Candidates and what was verified

Commits/versions: IronCalc `d50f26e0bc61…` (workspace 0.9.1, cloned 2026-11-13); tested binary was the
**PyPI wheel `ironcalc 0.9.1` (cp312 manylinux), not built from that commit; correspondence not
verified.** GridCraft `c0ee120ac2d9…` (2026-11-12). Gridline `059a06ab780d…` (2026-02-24).
openpyxl 3.1.5 (wheel). Shallow clones: I did not examine history or issue trackers.

| Criterion | IronCalc | GridCraft | Gridline | openpyxl (parse baseline) | `formulas` / `pycel` |
|---|---|---|---|---|---|
| License (read in repo/package) | `LICENSE-MIT` + `LICENSE-Apache-2.0`; crates declare `MIT OR Apache-2.0` | `LICENSE-MIT` + `LICENSE-APACHE` + `NOTICE`; `Cargo.toml` `MIT OR Apache-2.0`. A third-party article claims GitHub shows Apache-2.0 only; the repo files show both. Brand assets (ArtCraft logos) are trademark with separate terms | `LICENSE-MIT` + `LICENSE-APACHE`; crate `MIT OR Apache-2.0` | `LICENCE.rst`, metadata MIT | **EUPL 1.1+** / **GPLv3** (LICENSE file + classifier): **disqualified** |
| Dependencies | 137 registry crates in `Cargo.lock`; crates.io metadata: all permissive (MIT/Apache/Unlicense/ISC/Zlib/BSL-1.0; one `MIT OR Apache-2.0 OR LGPL-2.1-or-later` offers a permissive choice; one adds Unicode-3.0). Metadata only, not each crate's LICENSE file; lock covers the whole workspace incl. wasm/node/python | 672 locked packages (GUI-heavy). **Not audited** | 388 locked packages. **Not audited** | `et-xmlfile` | n/a |
| Maturity | version 0.9.1, "work in progress" per README; I did not review issues/tests | self-described **alpha**; ROADMAP: next stage (beta) estimated ~160–240 h away; repo reported to be weeks old | v0.3.3, terminal app | very mature, widely used (not verified here) | n/a |
| Build | **not built** (no Rust toolchain; rustup not reachable from my sandbox). Wheel installed | not built | not built | n/a | n/a |
| Fit | Python bindings exist (PyO3); Rust engine + xlsx reader/writer | desktop/WASM app, CLI and MCP; no Python binding seen. Integration would be a subprocess | formulas are **Rhai scripts**, no `xlsx` dependency: **idea source only** (confirmed) | pure Python | n/a |
| XLSX round-trip + unknown parts | see 3.1 | **not tested**; README-level claims only (docs list R/W of cells, formulas, charts, pivots; none verified) | n/a | see 3.2 | n/a |
| Formulas | see 3.3 | **not tested** (docs claim 513 functions: unverified) | n/a | does not evaluate | n/a |
| Performance | see 3.4 | not tested | n/a | see 3.4 | n/a |
| Security | see 3.5 | not tested | n/a | **not tested** | n/a |
| Extractability | MIT/Apache permit reuse with notice, but I recommend binding, not copying | same license caveat, plus trademark assets must not be reused | idea only | n/a | no |

`THIRD_PARTY_NOTICES.md` should be updated by Agent 0 with the verified licenses above (I may not edit it).

## 3. Evidence

### 3.1 IronCalc XLSX round trip (fixture `extras.xlsx`, generated from raw XML)
Fixture: 14 parts incl. `customXml`, a pivot cache definition stub, a drawing, `vbaProject.bin`,
sheet-level merge/conditional format/data validation/`extLst`, an RTL sheet, a Persian sheet name,
a defined name, an error cell, formulas. Load, `evaluate()`, `save_to_xlsx`:
- **0 of 8** parts of the plain fixture byte-identical; the package is regenerated (adds
  `docProps`, `theme`, `metadata.xml`, and bare directory entries such as `xl/`).
- **Lost parts:** `customXml/*`, drawing + its rels, pivot cache definition, `vbaProject.bin`.
- **Lost inside kept parts:** data validations, `extLst`, **`rightToLeft` sheet view**, the
  macro-enabled content type, the drawing reference.
- **Kept:** merged cells, conditional formatting, formulas, column width, row height, defined name,
  Persian sheet name, bool and error cells, date number format.
- Corollary: IronCalc as the XLSX writer would violate the "preserve unknown parts" rule and would
  silently discard the RTL flag for Persian workbooks. Using it only as a calculator avoids this.

### 3.2 openpyxl (3.1.5, `keep_vba=True`)
Lost: `customXml/*`, drawing + rels, pivot cache definition; `extLst` removed with a warning. Kept:
RTL, data validation, conditional formatting, merges, macro-enabled content type, and the VBA part
byte-identical. Conclusion: better than IronCalc on fidelity, still not a preserving writer, so it
cannot be our export path either. (The first run failed on my own fixture, which lacked a `dxfs`
section; fixed, and results above are from the corrected fixture. LibreOffice and IronCalc had
tolerated the flaw; this is a robustness difference worth keeping in mind for our reader.)

### 3.3 Formula sample, IronCalc vs LibreOffice (107 formulas, no cached values)
IronCalc equals LibreOffice on **91**; the **16** differences are all explained, none a confirmed IronCalc error:
- 9: my fixture wrote newer functions without the `_xlfn.` prefix that Excel files use
  (`IFS`, `CONCAT`, `XLOOKUP`, `SWITCH`, `TEXTJOIN`, `UNIQUE`, `FILTER`, `LET`, `SEQUENCE`); LibreOffice says `#NAME?`,
  IronCalc accepts them. **Our own formula reader must handle `_xlfn.`/`_xlws.` prefixes.**
- 2 formatting only (`DATE`, `10%`); 2 error-name differences (`Err:502` vs `#NUM!`/`#VALUE!`).
- 3 where LibreOffice deviates from documented Excel behavior and IronCalc matches Excel:
  `TRUE&"x"` gives `TRUEx`; `SUM("3",1)` and `SUM(A1:A8,"3")` count the text argument.
- `(0.1+0.2)-0.3` is 5.55e-17 in IronCalc (as in Excel), 0 in LibreOffice.
- Spill: `UNIQUE(A1:A8)` and `SEQUENCE(2)` returned only the first element through `get_cell_value`.
Caveats: LibreOffice is a secondary oracle, not Excel; 107 formulas is a sample, not coverage; I did
not count IronCalc's supported functions (README figures are dated and unverified).
Also: loading formulas without cached values makes IronCalc print `Unexpected type (empty)` once per cell.

### 3.4 Performance (100k rows x 20 columns, ~1.9 M cells, 100k formulas)
| Test | Result |
|---|---|
| IronCalc `load_from_xlsx` (15.5 MB file, 50k unique strings) | **1.11 s**, max RSS 137 MB |
| `evaluate()` (100k formulas) | 0.20 s |
| Read 1000x20 cells through per-cell Python calls | 6 ms |
| Edit one cell + `evaluate()` | 0.21 s (re-evaluates the workbook; I did not find targeted recalculation in the raw API) |
| `save_to_xlsx` | 1.66 s, max RSS 419 MB |
| Feed 1.9 M cells from Python through typed setters | **0.71 s**, max RSS 195 MB |
| openpyxl normal-mode load of the same file | **14.7 s**, max RSS 793 MB |
| My pure-Python probe: eager parse of `<sheetData>` only (BENCHMARKS.md) | 5.75 s lower bound; lazy index 0.10 s |
Not apples to apples: the probe file differs from this one (more string references, no shared-string
table parse). The direction is clear: a Rust core is roughly 5x faster than eager pure Python on open,
and openpyxl is slower still. This supports lazy materialization either way (PLAN section 0.3), and
makes IronCalc attractive for recalculation, not for I/O. Feeding cells is cheap, so Option A's
duplicate-model cost is mostly memory (~195 MB for this size), not time.

### 3.5 Hostile input against IronCalc's loader (3 GB address-space limit)
- **Zip bomb** (1.5 MB zip, 1.5 GB of whitespace in a sheet): loaded without error, **max RSS 1,518 MB**.
  No decompression budget: the safe zip layer must be ours (PLAN section 10) in every option.
- **XXE** (`<!ENTITY ... SYSTEM "file:///etc/hostname">`) and **billion laughs**: rejected with an XML error
  (entities not expanded; no file content in the cell).
- **Path-traversal entry names** (`../../evil.txt`, `/abs/...`): file loaded; entries are read by name and
  nothing was written to disk in this test (I only checked that no error or write occurred, not the code).
- Cell `XFD1048576` accepted in 0.0 s; `XFE1048577` rejected with a typed error.
openpyxl was not run against these.

### 3.6 Pure-Python libraries
`formulas` 1.3.4 is **EUPL 1.1+**; `pycel` 1.0b30 is **GPLv3**: both copyleft, excluded. `xlcalculator`
0.5.0 declares MIT; not evaluated further (pure Python would not beat my own baseline on speed).

## 4. Options, as evidence now stands
- **A. Own package layer + bind IronCalc** — leading. Needs: Rust in build, a pinned and hash-verified
  wheel or a source build, a thin adapter that keeps our store and IronCalc's model in sync, answers to
  the open items in 1.4.
- **B. Subprocess JSON-RPC** — avoids PyO3/ABI coupling and gives process isolation (ADR-011), but each
  recalculation moves cells across a pipe; not measured. Fallback if binding is awkward.
- **C. Own pure-Python evaluator** — no dependency or license question, slow at 100k formulas, needs
  months of function work. Remains the reference implementation for tests and the fallback.
- **D. Wrap a single library** — rejected: no candidate preserves unknown parts.

## 5. Risks of the leaning choice
IronCalc is pre-1.0 and self-described work in progress; a single small maintainer base (not verified);
wheel provenance vs source; spill and dynamic arrays unproven; model duplication in memory; Rust build
in CI; semantics must still be cross-checked against real Excel files, which I cannot obtain.

## 6. Provenance
Code read: none copied, adapted or vendored. Ideas used from candidates: none yet. Files read in
candidate repos: LICENSE*, NOTICE, Cargo.toml, Cargo.lock, README/ROADMAP/ATTRIBUTION headings,
`docs/file-format-parity.md` (GridCraft). Third-party web pages were used only to locate repositories
and are not evidence for any claim above. The tested IronCalc binary is the PyPI wheel noted in section 2.
