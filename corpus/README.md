# Test corpus

Real-world and hostile OOXML files for Agent 1's engine tests (import, round trip, compatibility report, limits).

- `apache-poi/` — 29 workbooks from Apache POI `test-data/spreadsheet/` (commit in `manifest.json`). Licence: Apache-2.0 (`LICENSE-Apache-2.0.txt`, `NOTICE-Apache-POI.txt`). Chosen for features: pivots, charts, VBA (`.xlsm`, never executed), tables and structured references, conditional formatting, data validation, external links, array formulas, 1904 dates, large cell counts.
- `hostile/` — 18 corrupt, fuzzer-minimized or encrypted files. Expected result: a typed rejection or a report, never a crash or hang.
- `manifest.json` — per file: path, sha256, size, source URL, why it is here, feature counts (from our own scan, not from Excel).
- `private/` — **gitignored.** Put your own files here (for example the Contextures budget workbook, which has an informal licence). Tests that need them must skip when absent.

## Caveats
- POI is a test suite for Java code: some files are synthetic or edited by POI itself, not made by Excel. `manifest.json` records the producing application where the file states it.
- Apache-2.0 is the licence of the POI repository; individual files may have other origin. Files that looked third-party (real KYC or crossref documents) were left out. If you doubt one, remove it.
- Not covered: a Persian workbook with an RTL sheet view (`right-to-left.xlsx` has Arabic text only), and a true Excel-made 100k x 20 file.

Feature counts and the "good" label mean "useful for testing", not "supported".
