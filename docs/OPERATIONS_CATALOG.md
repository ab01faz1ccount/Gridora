# Gridora — Operations Catalog (initial scope)

Every operation is registered via an `OperationDescriptor`. All are previewable unless noted. "Destructive" ones require explicit confirmation. Status for every row is **Planned** until the module status table says otherwise.

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
- Operations that create new data (`group_aggregate`, `pivot`, `join`, …) return `output` and never overwrite the source.
- New operations are added by registering a descriptor and an implementation; no UI change needed.
