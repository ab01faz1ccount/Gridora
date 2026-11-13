# Gridora — Persian-first / RTL Specification

Owner decision: the UI is Persian-first with RTL from day one (ADR-009).

## Language and layout
- Default locale `fa`; English `en` as fallback. Every user-visible string comes from a catalog (`apps/web/src/i18n/{fa,en}.json`); none hard-coded.
- Use CSS logical properties (`margin-inline-start`, `inset-inline-end`, …), never left/right for layout.
- `dir="rtl"` on the document for `fa`; icons that imply direction (arrows, undo/redo) are mirrored.
- Persian-capable font bundled locally (no CDN; the deployment must work offline).
- Mixed content (Latin formulas, numbers, file names) uses `bdi`/`unicode-bidi: plaintext` so it renders correctly inside RTL text.

## Grid
- Sheet direction follows `SheetMeta.rtl` (Excel's right-to-left view); column A is on the right when `rtl` is true. Keyboard arrows follow visual direction.
- Formula bar and cell editor are LTR for formula text, RTL for plain text.

## Digits
- Storage is always canonical Latin digits and ASCII-safe numeric values.
- Display option: Latin, Persian (۰-۹) or Arabic-Indic digits, per user setting.
- Input accepts all three; normalized before parsing.

## Dates
- Storage is Gregorian/Excel serial.
- Display option: Gregorian or Jalali (Solar Hijri). Jalali conversion is a display and an explicit operation; the conversion library choice is recorded in DECISIONS.md.
- Number-format codes written back to XLSX stay Excel-compatible; Jalali display is Gridora-side and must be flagged in the compatibility report when it cannot round-trip.

## Text cleaning (operations)
- Normalize Arabic `ي`→`ی`, `ك`→`ک`, remove tatweel/ZWNJ-aware options, digit normalization. Never applied silently; always a user-chosen operation with preview.

## Sorting and search
- Persian-aware collation for sort; search ignores ي/ی and ك/ک differences when the user enables "ignore variants".

## Testing
- Snapshot tests of key screens in RTL; fixture files with Persian sheet names, text and digits; round-trip through XLSX and CSV (UTF-8 with BOM and Windows-1256).
