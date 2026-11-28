# Gridora — Operations Catalog (initial scope)

Every operation is registered via an `OperationDescriptor`. All are previewable unless noted. "Destructive" ones require explicit confirmation. All fifteen operations are implemented in `packages/dataops`; see [REFERENCE.md](REFERENCE.md).

| Category | Operation `type` | What the user sees | Targets | Destructive |
|---|---|---|---|---|
| Order | `sort` | Sort by one or more columns, asc/desc, Persian-aware | sheet, table | No (undoable) |
| Select | `filter` | Show rows matching conditions (text, number, date, empty) | sheet, table | No |
| Clean | `remove_duplicates` | Remove duplicate rows by chosen columns | sheet, table | **Yes** |
| Clean | `find_replace` | Find/replace in range or column, whole-cell or partial | sheet, table | **Yes** |
| Clean | `fill` | Fill empty cells down/up/with value | sheet, table | No |
| Clean | `clean_text` | Trim, case change, remove extra spaces, normalize Persian/Arabic letters and digits | sheet, table | **Yes** |
| Reshape | `split_column` | Split by delimiter/fixed width into columns | sheet, table | **Yes** |
| Reshape | `merge_columns` | Combine columns with a separator | sheet, table | No |
| Reshape | `change_type` | Convert column to number/text/date | sheet, table | **Yes** |
| Calculate | `computed_column` | New column from the GUI expression builder (arithmetic, text, conditionals) | sheet, table | No |
| Analyze | `group_aggregate` | Group by columns; sum/avg/count/min/max | table → new table/sheet | No |
| Analyze | `pivot` | Rows, columns, values, aggregation | table → new table/sheet | No |
| Analyze | `unpivot` | Wide to long | table → new table | No |
| Combine | `join` | Merge two tables on keys (inner/left/right/outer) | table + table | No |
| Dates | `convert_calendar` | Gregorian ↔ Jalali | sheet, table | **Yes** |

Rules:
- Params are JSON Schema validated; the UI form is generated from the schema.
- `computed_column` uses a structured expression tree, not free-text scripting (ADR-007).
  - Functions by category (the schema lists them under `x-gridora-functions`, one row each in `FN_META`):
    **math** add sub mul div mod neg abs floor ceil round(number, digits?) min2 max2 between;
    **text** concat upper lower trim len left right substring replace fold contains starts_with ends_with;
    **logic** eq ne lt le gt ge and or not if switch is_null coalesce;
    **date** year month day days_between add_days;
    **convert** to_number (digits of any script, thousands separators; decimal separator `.` unless `","` is given) to_text.
  - Behaviour worth knowing: `round` goes half away from zero (2.5 → 3, -2.5 → -3); `div`/`mod` by zero leave an empty
    cell and a `division_by_zero` warning; `to_number` leaves non-numbers empty with a `number_parse_failed` warning;
    a negative count in `left`/`right`/`substring` gives empty text; text made from numbers shows 15 significant digits
    (0.1 + 0.2 → `0.3`); integer literals beyond 2^53 are refused rather than silently rounded; `min2`/`max2` and all
    other arithmetic leave an empty cell empty (use `coalesce` for a stand-in); `round` with digits works on the decimal
    value you see (`round(1.005, 2)` → 1.01, as in a spreadsheet).
- Behaviour worth knowing (each is pinned by `tests/test_dataops_realworld.py`):
  - `join`: integer keys are compared exactly (never as floats); null keys never match; duplicate keys multiply rows (capped);
    text keys can ignore spaces (`trim`), English case (`case_sensitive: false`) and Arabic/Persian letter variants;
    a suffix that would create a duplicate column name is an error at `/params/suffix`.
  - `change_type` to date: a text such as `1403/01/01` is a Jalali date, not the year 1403 — it counts as unconvertible
    (with a `dates_look_jalali` warning); read it with `convert_calendar` `from_jalali`. Numbers become text with at most
    15 significant digits, integers from 10^15 up in full; an empty boolean stays empty.
  - `fill` constant on all columns skips the columns the value does not fit (`fill_skipped_columns`); on chosen columns it
    names the column that cannot take it. `remove_duplicates` does not trim: run `clean_text` first (empty cells count as one).
  - `split_column` keeps the empty first part of a leading delimiter, as a spreadsheet's text-to-columns does.
- Operations that create new data (`group_aggregate`, `pivot`, `join`, …) return `output` and never overwrite the source.
- New operations are added by registering a descriptor and an implementation; no UI change needed.
