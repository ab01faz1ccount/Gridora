# Gridora — UX Specification (v1)

Owner: Agent 0. Implementer: Agent 3 (`apps/web`), with Agent 2 supplying operation metadata. Status: **specification, not yet implemented.** Written 2026-11-17 against `main` after PR 7 (grid) and before PR 8 (import UI).

This document says how the product should *feel and flow*. Technical grid, RTL, state and API decisions stay in `apps/PLAN.md`; where they overlap, `apps/PLAN.md` wins on mechanics and this file wins on user-visible behaviour. The owner will refine this after hands-on testing; every section marked **[TEST]** is a place where real use should overrule my guesses.

## 1. Principles

1. **Familiar surface, simpler power.** The sheet looks and behaves like Excel (cells, A1 headers, sheet tabs, formula bar, the usual keys). Power features are reached by *saying what you want to do*, not by memorising menus.
2. **Nothing happens silently.** Every change can be previewed before it is applied (operations) or undone after (everything). Every loss during import/export is shown in plain words.
3. **Persian first, honestly.** Persian copy is written for a non-technical reader, not translated from English. No raw error codes in the user's face; the code is available under "details".
4. **The server is the authority; the screen is never frozen.** Edits feel instant (optimistic), long work shows progress and can be cancelled.
5. **Fewer, better controls.** No ribbon with 100 buttons. A small toolbar, a task search, a side panel. Anything not implemented is **absent or clearly disabled with a reason**, never a button that fails.
6. **Do not mimic Excel where Excel is wrong for this audience** (silent value changes, cryptic `#VALUE!`, destructive actions without a preview, hidden history).

## 2. Who it is for (design targets)

- **Newcomer:** knows what a table is, not what a function is. Wants "remove duplicate rows", "sort by name", "total per city". Must succeed without reading help.
- **Excel user:** wants familiar keys and does not want to be slowed down. Must be able to ignore all the guided features.
- Both use Persian by default; many files contain mixed Persian/English/digits (Persian ۱۲۳, Latin 123, Arabic-Indic ١٢٣).

## 3. Screen layout (RTL default; mirrors automatically in LTR)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Top bar:  [name ▾]  saved ✓ / saving… / error      ↶ ↷   [Find ⌕]  [⋯] │
├──────────────────────────────────────────────────────────────────────┤
│ Task bar:  [ What do you want to do?  ⌕ ]   Sort  Filter  Chart  …    │  <- selection-aware
├──────────────────────────────────────────────────────────────────────┤
│ Formula bar:  [A1 ▾]  [ fx  value or =formula                      ]  │
├───────────────────────────────────────────────┬──────────────────────┤
│                                               │ Side panel (start     │
│                  GRID                         │ side): Operation /    │
│                                               │ History / Import      │
│                                               │ report / Data Tables  │
├───────────────────────────────────────────────┴──────────────────────┤
│ Sheet tabs  [Sheet1] [Sheet2] [+]        selection summary: count/sum │
└──────────────────────────────────────────────────────────────────────┘
```

- **Side panel** opens on the start edge (right in RTL). One panel at a time; closing it never loses state. Width 320–400 px; on screens under 900 px it becomes a bottom sheet.
- **Selection summary** (status bar): count, sum, average of the selected numeric cells; read-only, computed client-side from loaded blocks only and labelled "visible cells only" when the selection exceeds loaded data **[TEST]**.
- **No ribbon.** Replaced by the task bar (below). If the owner finds this too sparse after testing, a tabbed ribbon can be added later without changing the engine or API.

### 3.1 Task bar (the main idea)

- **Search box "What do you want to do?"** searches the operation catalog by *Persian task phrases*, not only operation names: typing "تکراری" finds *Remove duplicates*; "مجموع هر شهر" finds *Group and total*. Results show the Persian title, one-line description and an example. Enter opens the operation panel.
- **Suggested chips** (3–6) change with the selection: a column of text → Sort, Clean text, Split; a numeric range → Sort, Total, Chart; a whole table-like range with a header → Filter, Remove duplicates, Group; a cell with an error → "Explain this error".
- The chips and search results come from `OperationDescriptor` plus the i18n catalog (keywords/synonyms keys, see `docs/reviews/REVIEW_5_ORDERS.md`). The client never hard-codes the list of operations.

## 4. Core flows (acceptance scenarios; each must be walkable in the browser)

Each flow is also a Playwright test once its pieces exist.

**F1. Open a file.** Drop or choose a `.xlsx`/`.csv`. Progress with file name and size → "Opened. N items need your attention" with a link to the report, or straight to the grid if nothing was lost. Unsupported (`.xls`, encrypted, corrupt) gives a plain Persian message that says *what* and *what to do* ("این قالب قدیمی پشتیبانی نمی‌شود؛ فایل را در اکسل به .xlsx ذخیره کنید"), not an error code.

**F2. Edit and undo.** Type in a cell; Enter commits and moves; the value shows instantly; "saving…" turns into "saved ✓". Ctrl+Z / Ctrl+Y (and the ↶ ↷ buttons) walk the history. A conflict (`version_conflict`, 409) shows a non-blocking banner "این برگه در جای دیگری تغییر کرده؛ بازخوانی" and never discards the user's typed text silently.

**F3. Remove duplicates (or sort/filter).** Select a table-like range or a column → chip or search → panel shows: *where* (range, editable), *which columns count*, options in plain words → **live preview** of the result (first N rows, "X rows would be removed") → **Apply** → toast "۱۲ ردیف حذف شد · واگرد" with Undo. For operations that destroy data, the Apply button text states the effect ("حذف ۱۲ ردیف") and, if the range has formulas, the panel explains the choice (refuse by default; "convert to values" must be an explicit checkbox with the consequence written next to it).

**F4. Too big for the sheet.** When an operation on a big sheet range returns `operation_conflict` with detail `too_large_for_history`, the message is: "این کار روی کل برگه خیلی بزرگ است و واگرد ندارد. می‌توانید آن را به «جدول داده» تبدیل کنید و آنجا انجام دهید." with a primary button **Convert to Data Table** (calls `from-range`), then the operation is offered again on the table. Never show the code.

**F5. Total per group, then chart.** Group-and-total panel → result opens as a new Data Table (or new sheet area, per operation) → "Make a chart" chip → chart spec form (type, category, value) with live preview → chart appears in a panel/sheet. Digits and axis follow the display preference (Persian digits by default).

**F6. Save/export.** "Export as .xlsx" runs as a job, then offers the download plus the **export report** (what could not be written, and the line "formula results were not recalculated" when it applies). Gridora autosaves its own working copy; "export" is explicit.

**F7. Reuse (Tools).** After a sequence of operations: "Save these steps as a tool" → name, choose which values (column, text) become inputs → later "Run tool" asks only for those inputs, with preview. Phase-3 slice 8; not before F1–F6.

## 5. The operation panel (one pattern for all 15+ operations)

1. **Title + one sentence** of what it does, and "Example" (a before/after mini table, from the catalog).
2. **Where:** the target (selected range or Data Table), shown as editable text and highlighted on the grid.
3. **Fields** generated from `params_schema` (`x-gridora-*` hints). Plain words, sensible defaults, advanced options collapsed under "More options".
4. **Preview** (auto, debounced; first rows + counts + warnings). A spinner and a cancel link for slow previews. If the server says it cannot preview, say so, do not fake one.
5. **Apply** with an effect-stating label; destructive operations need one extra click only when the effect is irreversible or large (> a threshold from the server's `OperationResult`/descriptor flag), never as a generic "Are you sure?".
6. **After:** toast with Undo; the panel stays open with "Apply again / Close".
7. **Errors** are attached to the field by JSON pointer (`ValidationError.path`); the message comes from the catalog. A field the form renderer does not understand is shown as a labelled raw-JSON box with the text "این گزینه هنوز فرم ندارد" (graceful fallback), never dropped.

## 6. Messages and tone

- Short, concrete, active. State what happened, then what to do. Example shapes: success "۱۲ ردیف تکراری حذف شد"; blocked "نمی‌شود چون … ؛ می‌توانید …"; loss "این قسمت از فایل نگه داشته شد ولی قابل ویرایش نیست".
- Numbers in the user's chosen digit set; dates in Jalali or Gregorian per preference; units not abbreviated.
- Error values in cells (`#DIV/0!`, `#VALUE!` …) keep Excel's symbol (users know it) and get a tooltip/"Explain" in Persian with the likely cause. The symbol itself is never translated.
- The compatibility panel shows the engine's statuses verbatim in meaning (`preserved` / `editable` / `dropped`…), grouped, with locations ("Sheet العمليات, F12"). The UI must not soften them.

## 7. Keyboard and input

- Standard keys per `apps/PLAN.md` §3.3. In an RTL sheet ArrowRight moves to the *previous column* (visual direction); Ctrl+Home/End, Ctrl+arrow data-edge jump come later (needs data beyond loaded blocks).
- Global: `Ctrl+Z/Y` undo/redo, `Ctrl+F` find, `Ctrl+K` (or `/` when not editing) opens task search, `Esc` closes panel/cancels edit, `F2` edit, `Ctrl+Enter` apply in the operation panel.
- **Digit input:** typing Persian/Arabic-Indic digits into a numeric cell is normalised to numbers (the value is a number; display follows preference). Pasting text with ي/ك is stored as typed in cells; operations such as *Clean text* normalise on request. Never silently rewrite what the user typed.
- **IME:** composition must not commit on Enter mid-composition. Cell editor `dir` follows content (LTR when starting with `=`).
- Every action reachable by keyboard; visible focus ring; tab order follows reading order (mirrored in RTL).

## 8. States every screen needs

| State | Behaviour |
|---|---|
| Empty workspace | One big "فایل را اینجا بکشید یا انتخاب کنید" drop zone and "شروع با جدول خالی" |
| Loading blocks | Skeleton cells in the missing area, never a blank grid; scroll never blocks |
| Large file | Show size and progress; "this may take a minute" after 5 s; cancel always available |
| Long job (whole-sheet op, import, export) | Job card with status, progress when known, Cancel; survives page reload by job id |
| Offline / API down | Banner, edits queued only if the design allows it (v1: **not queued**; edits are disabled with a message) |
| Session expired | Re-login dialog that returns to the same place |
| Read-only (protected sheet, `sheetProtection` in file) | Visible lock icon; edits refused with the reason; this is a file property, not a permission system |
| Disabled feature | Absent if not planned; greyed with a tooltip stating *why* if planned ("بعد از نسخه ... "); never an enabled button that errors |

## 9. Accessibility and display

- WCAG 2.1 AA target: contrast, focus visibility, labels for icon buttons, `aria-live` for toasts and save status, grid roles per the ARIA grid pattern as far as virtualization allows (document the gaps).
- Light and dark theme from tokens; default follows the OS. Font stack with a good Persian face (Vazirmatn is OFL, bundled locally, **no CDN**; record it in THIRD_PARTY_NOTICES). Sizes in rem; zoom to 200% without horizontal page scroll.
- Density: Comfortable (default) / Compact; remembered per user.
- Nothing may load from the internet at runtime (fonts, icons, analytics included).

## 10. What v1 deliberately does **not** do in the UI

Ribbon, macros UI, add-ins, pivot-table *editor* (pivots in files are preserved; the `pivot` *operation* produces a new table), conditional-format and data-validation *editors* (preserved, shown as read-only badges), collaborative cursors, comments editor, fill handle, drag-fill, multi-range selection, split/freeze panes beyond what the engine exposes. Each missing item that a file contains is reported at import, not hidden.

## 11. Mapping to work (so the spec does not float)

| Agent 3 PR | UX content it must include | Depends on |
|---|---|---|
| 8 `web-import` | F1, empty state, job card, compatibility panel, unsupported-format messages | Agent 1 report fields |
| (wire real engine) | F1/F2 with `GRIDORA_ENGINE=real`, e2e upload → window → edit → undo | Agent 1 E5/E6 |
| 10 `web-edit` | F2, history panel, conflict banner, save status | api-history |
| 11 `web-operations` | task bar, §5 panel, F3, F4, toasts with Undo | Agent 2 descriptor metadata |
| later | F5 charts, F6 export, F7 Tools, Data Tables view | slices 5–8 |

Agent 3: do **not** build the task bar or the operation panel before PR 11; build the shell regions (top bar, formula bar, side panel host, sheet tabs, status bar) in PR 8/10 so nothing is rebuilt later.

## 12. Owner test protocol (when the first integrated build exists) **[TEST]**

Run on a real laptop, Persian UI, with the corpus files in `corpus/private/` and `corpus/apache-poi/`. For each task note: did it work, how many clicks/seconds, where you hesitated, what text confused you, anything that looked wrong in RTL.

1. Open `softwiro-piece-rate-payroll.xlsx`: do all 7 sheets look right-to-left? Is anything missing compared to Excel? Read the report.
2. Edit one cell, undo, redo, reload the page: is the state right?
3. Open `file_example_XLSX_5000.xlsx`: scroll fast, jump to row 4000, select a column.
4. Remove duplicates on a column (preview first, then apply, then undo).
5. Open the `.xls` file and a corrupt file from `corpus/hostile/`: is the message understandable?
6. Export and open the result in real Excel: any repair prompt?

Record results in a file `docs/reviews/UX_TEST_1.md` (template: task, result, time, notes, severity). Severity scale: **blocker** (cannot complete), **major** (completes with confusion), **minor** (cosmetic).

## 13. Open questions for the owner

- Ribbon-less layout (task bar + side panel): acceptable, or do you want a tabbed toolbar too?
- Default digits in cells: follow the file (as typed) or always Persian? (Spec assumes: as typed; display preference switches rendering only.)
- Jalali dates: display-only conversion (default), or also a Jalali date picker in cells?
- Should "Convert to Data Table" be offered earlier (for files over ~50k rows) rather than only after the cap error?
