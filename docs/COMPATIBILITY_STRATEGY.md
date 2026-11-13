# Gridora — Excel Compatibility Strategy

Goal: long-term full Excel compatibility. **Gridora does not claim full compatibility until it is verified against a corpus.** Until then every file gets a report.

## Tiers per feature

| Tier | Meaning |
|---|---|
| Supported | Read, editable, written back correctly |
| Partial | Read/edited with known differences (documented) |
| Preserved | Not understood, but original XML is kept and written back untouched |
| Unsupported | Cannot be kept; user is warned before it is lost |

"Preserved" is the default fallback; "Unsupported" is the exception and must always produce a warning, never a silent drop.

## OOXML package layer

- XLSX is a zip of parts plus relationships. The engine models the *package*, not only cells.
- Unknown parts (and their `.rels`, content types) are kept as opaque blobs and re-emitted byte-for-byte.
- On save, only parts we changed are regenerated (dirty-part strategy): sheet XML for edited sheets, `sharedStrings`, `styles` as needed.
- Cross-part dependencies (e.g. edits that invalidate a pivot cache, table definitions, charts referencing ranges) are tracked; when an edit may invalidate a preserved part, the user is warned.

## Feature registry

A versioned list of codes (`xlsx.pivot_table`, `xlsx.vba_project`, `xlsx.conditional_format.icon_set`, `xlsx.external_link`, …) each with tier, handling, and test fixtures. The import report is generated from it. The registry is the single source of truth for what the README may claim.

## Formulas

- Evaluate a defined function subset first; unsupported functions keep their cached value, show `#NAME?`-style warnings in Gridora, and are written back unchanged.
- Function coverage is tracked in a table generated from tests, not hand-written.
- Disallow network/external-data functions and external-workbook links by default (security).

## Verification

- Fixture corpus: hand-built files + files exported from Excel and LibreOffice.
- Round-trip test: import → export → re-import → compare cells, formulas, styles; unknown parts byte-equal.
- Where Excel itself is unavailable, LibreOffice is a secondary oracle and this limitation is documented.

## Candidate libraries (research status: README-level only, not code-audited)

| Candidate | Reported license | Notes |
|---|---|---|
| GridCraft (storytold/gridcraft) | Apache-2.0 / MIT per README | Rust, self-described alpha, egui desktop/WASM app; claims XLSX round-trip. Star count unverified; maturity claims must be tested. |
| Gridline (ali-raheem/gridline) | MIT OR Apache-2.0 | Terminal spreadsheet with Rhai formulas; likely poor fit as an Excel-compat engine; idea source only. |
| IronCalc | MIT OR Apache-2.0 | Rust engine with XLSX reader/writer and Python/WASM bindings advertised; self-described early stage. Strongest candidate for a spike. |

Decision deferred to ADR-003 after the Phase 2 spike. See THIRD_PARTY_NOTICES.md for provenance rules.
