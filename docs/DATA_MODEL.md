# Gridora — Data Model & Shared Representations

Types are written as TypeScript-style pseudo-schemas; the normative form is `contracts/` (pydantic for Python, a mirrored `index.ts`).

Conventions: IDs are UUIDv4 strings. Rows/columns on the wire are **0-based integers**. A1 notation appears only inside formula text and UI labels. Timestamps are ISO-8601 UTC. All schemas carry `schema_version`.

## 1. Workspace and files

```ts
Workspace  { id, owner_id, name, created_at }
FileRecord { id, workspace_id, owner_id, kind: "workbook"|"table"|"original",
             display_name, size_bytes, sha256, created_at,
             parent_id?: string }          // version chain; originals are immutable
```
Storage path is derived server-side from `owner_id` + `id`; never returned to clients.

## 2. Workbook

```ts
Workbook {
  id, file_id, name,
  sheets: SheetMeta[],            // ordered
  defined_names: DefinedName[],
  date_system: "1900"|"1904",
  compat: CompatibilityReport     // latest import/export report
}
SheetMeta { id, name, index, visible: "visible"|"hidden"|"very_hidden",
            row_count, col_count, frozen?: {rows:number, cols:number}, rtl: boolean }
DefinedName { name, scope: "workbook"|string /*sheet_id*/, ref: string }
```

## 3. Worksheet cells

Cells are sparse. The wire format for a window is columnar-friendly:

```ts
CellWindow { sheet_id, row0, col0, rows, cols,
             cells: Cell[] }           // only non-empty cells
Cell {
  r: number, c: number,
  v?: CellValue,                      // computed/stored value
  f?: string,                         // formula text, "=SUM(A1:A10)"
  s?: number,                         // style id
  t?: string                          // number-format id/hint
}
CellValue = { k:"num", n:number } | { k:"str", s:string } | { k:"bool", b:boolean }
          | { k:"err", e:"#DIV/0!"|"#N/A"|"#NAME?"|"#NULL!"|"#NUM!"|"#REF!"|"#VALUE!" }
          | { k:"date", iso:string }   // display convenience; stored as serial number internally
```
`Range = { sheet_id, r0, c0, r1, c1 }` (inclusive).

## 4. Structured Data Table

```ts
DataTable {
  id, workspace_id, name, version: number,
  columns: Column[], row_count,
  source?: TableSource                 // link back to sheet range, if any
}
Column { name, dtype: "int64"|"float64"|"bool"|"string"|"date"|"datetime"|"decimal",
         nullable: boolean, display_format?: string }
TableSource { kind:"sheet_range", workbook_id, range: Range, link: "snapshot"|"refreshable" }
```
- Contents are Parquet, immutable per version. Editing a table creates a new version.
- **Bridge:** `sheet → table` (header row detection, dtype inference with a preview and user override) and `table → sheet` (write values to a range/new sheet). Refreshable links re-run the import on demand; they never auto-overwrite user edits without confirmation.

## 5. Operations and pipelines

```ts
Target = { kind:"sheet_range", sheet_id, range: Range } | { kind:"data_table", table_id }

Operation {
  id, type: string,                    // key in the operation registry, e.g. "sort", "dedupe"
  schema_version, target: Target,
  extra_targets: Target[],             // e.g. right table of a join; API verifies ownership of ALL targets
  params: object                       // validated against the op's param schema
}

OperationDescriptor {                  // what the registry exposes; drives GUI forms
  type, label, category, description,
  params_schema: JSONSchema, targets: ("sheet_range"|"data_table")[],
  destructive: boolean, supports_preview: boolean
}

OperationResult {
  status: "ok"|"error",
  affected: { cells?: number, rows?: number },
  delta: Delta,                        // how to undo/redo (see §6)
  warnings: Warning[],
  output?: Target                      // e.g. a pivot creating a new table
}

Pipeline { id, name, steps: PipelineStep[], input_kind: "sheet_range"|"data_table" }
PipelineStep { type: string, schema_version: number, params: object, label?: string }  // flat; contracts/ is normative
// Tool bindings: a param value {"$input": "<name>"} is replaced at run time (bind_tool).
```
Execution contract (implemented by `dataops`):
`describe() → OperationDescriptor`, `validate(op) → ValidationError[]`, `preview(op, limit) → PreviewResult` (no mutation), `apply(op) → OperationResult`.

## 6. History, undo/redo

```ts
HistoryEntry { id, document_id, seq, operation: Operation, delta: Delta,
               label, created_at, undone: boolean }
Delta = { kind:"cell_patch", sheet_id, before: Cell[], after: Cell[] }       // sheet edits; includes recalculated dependents
      | { kind:"table_version", table_id, from_version, to_version }          // table edits; from_version 0 = "table was created"
      | { kind:"sheet_structure", ... }                                        // insert/delete/rename; defined by engine
```
Undo applies the inverse; redo re-applies. A new operation after an undo truncates the redo tail. History is per document, capped by size (default 500 entries or 200 MB of deltas), oldest entries are compacted into a snapshot version.

## 7. Reusable tools and workflows

```ts
Tool { id, owner_id, name, description, pipeline: Pipeline,
       inputs: ToolInput[], created_at }
ToolInput { name, kind:"column"|"range"|"value", label, required }   // parameters bound at run time
```
A Tool is a saved, parameterized Pipeline. Running a Tool binds its inputs to a Target and produces ordinary history entries. No scripting language in v1.

## 8. Chart specification

```ts
ChartSpec {
  id, document_id, type: "bar"|"line"|"pie"|"scatter"|"area",
  title?, source: Target,
  series: { name?, value_col, category_col?,
            aggregate?: "sum"|"avg"|"count"|"min"|"max"|"count_distinct"|"median" }[],
  options: { stacked?, legend?, axis_titles?: {x?,y?},                       // legacy
             stack?: "none"|"stacked"|"percent", orientation?: "vertical"|"horizontal",
             labels?: "none"|"value"|"percent", nulls?: "gap"|"zero", donut? },  // v0.7.0
  // v0.7.0, all optional:
  series_by?: column,                      // one series per value of this column (one `series` entry)
  filters?: { column, op, value?, value2? }[],   // AND-ed; same operators as the `filter` operation
  sort?: { by: "source"|"category"|"value", direction, order?: [..] },
  limit?: { top_n, end: "top"|"bottom", other?: boolean },
  time?: { granularity?: "day"|"month"|"quarter"|"year", calendar: "gregorian"|"jalali" }
}
ChartData { categories, series: {name, values: (number|null)[]}[],
            categories_kind?: "category"|"time"|"number", labels?: string[],   // v0.7.0
            notes?: { code, params }[], meta? }
```
A spec stores references and settings, never data. A spec saved before 0.7.0 loads unchanged: every new field is optional and absence means the old behaviour. `dataops` turns a ChartSpec + source into plain categories and series; the web app draws them (hand-written SVG, no chart library). The spec is renderer-independent.

`ChartProfile { rows, columns: ChartColumnProfile[], suggestions: ChartSuggestion[] }` answers "what is in this source and what chart fits" for the Chart Builder (`POST /documents/{id}/charts/profile`); `POST .../charts/preview` returns `ChartData` for an unsaved spec. Suggestions are optional and editable, never the only way to a chart.

Rules the engine follows (tested in `packages/dataops/tests/test_charts_engine.py`):
- **Empty is not zero.** A group whose values are all empty is empty (a gap), not 0; `nulls: "zero"` is an explicit user choice. Counts are real zeros.
- **Nothing disappears silently.** Rows or values a chart cannot draw (empty/unreadable dates, scatter points missing x or y, negative pie values, sampled points, Top N) are reported in `ChartData.notes`. Note codes: `rows_excluded {count, reason}`, `dates_unreadable {count, examples}`, `empty_values {count}`, `negative_values {count}`, `categories_limited {shown, total}`, `other_merged {count}`, `sampled {kept, total}`, `extra_series_ignored {count}`.
- **Time is time.** A date column (or a text column with `time` set) becomes a chronological axis in the chosen calendar; Jalali text dates in any digit script are read as dates. `labels` carry the display text (`1404/01`), `categories` the bucket start date (ISO).
- **Filters never touch the source**, they only change what the chart reads.
- **Top N** ranks categories by the sum of their series values; "Other" is only allowed for sums and counts and always comes last; it is refused on a time axis.
- **Scatter** shows rows as they are (no aggregate); above 5,000 points it keeps every k-th row (deterministic) and says so.

## 9. Validation errors and compatibility warnings

```ts
ValidationError { code, path: string /*JSON pointer into params*/, message, hint? }
Warning { code, severity:"info"|"warn", message, location?: string }

CompatibilityReport {
  source: "import"|"export", generated_at,
  items: CompatItem[],
  summary: { supported:number, partial:number, unsupported:number }
}
CompatItem {
  code: string,                        // stable, e.g. "xlsx.pivot_table"
  status: "supported"|"partial"|"unsupported",
  preserved: boolean,                  // original bytes kept for round-trip
  editable: boolean,                   // user can modify in Gridora
  location?: string, message: string
}
```
