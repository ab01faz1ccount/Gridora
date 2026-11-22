# apps/web — Gridora web app

Owner: Agent 3. Plan: [`../PLAN.md`](../PLAN.md). Contracts: imported from `../../contracts/typescript`
through the `@contracts` alias (never copied).

## Status: In progress (PR 6 skeleton, PR 7 grid, PR 8 import UI + workbook shell)

### What works (each item has a test)
- Vite + React 19 + TypeScript (strict, `noUncheckedIndexedAccess`). `npm run check` = typecheck + lint + tests.
- **API client** (`src/api/client.ts`): unwraps the success envelope; every failure becomes an
  `ApiError` (code, status, request id, `Retry-After`); CSRF header on mutating calls only; dropped
  connection -> `network`; non-JSON body -> `internal_error`; a 401 outside the sign-in calls reports
  "session gone". Server message text is never shown to users: errors map to catalog keys.
- **Sign-in / sign-out / session restore** via `AuthResult` (`/auth/login`, `/auth/me`, `/auth/logout`);
  the CSRF token lives in memory only. Wrong password and rate-limit (with wait time) have their own
  localized messages.
- **Workspaces**: list, create, rename (dialog), delete (confirm dialog; sends `?confirm=true`).
- **i18n**: `fa.json` / `en.json` with compile-time key parity, placeholder-parity test, a message for
  every contract error code. Persian + RTL by default; the language switch flips `lang`/`dir`.
- **Display preferences** (client-side, `localStorage` guarded for blocked/corrupt storage): language,
  digit set (Latin / Persian / Arabic-Indic), calendar (Gregorian / Jalali via `Intl`). Wire and stored
  values stay Latin; `normalizeNumericInput` accepts Persian/Arabic digits and separators but never
  rewrites formulas, digits inside words, or ambiguous input like `1,5`.
- **Fonts**: Vazirmatn (SIL OFL 1.1, license shipped in `public/fonts/OFL.txt`), bundled, no CDN.
- **RTL**: CSS uses logical properties only; a test fails on any physical left/right/width/height.
- **No hard-coded UI text**: a TypeScript-AST test fails on literal text or `title/placeholder/aria-label`
  strings in components (and the scanner itself is tested).
- **Accessibility basics**: labelled form fields, `role=alert` errors, modal dialogs with focus trap,
  Escape to close and focus restored to the opener.
- **Stub badge**: shown only when the server reports `X-Gridora-Engine/Dataops: stub`.
- `vite build` succeeds (~86 kB gzip JS).

### Grid (PR 7)
- Route `/workbooks/<id>`: sheet tabs and a virtualized, DOM-based grid; `src/grid/`.
- **Windowing**: only visible rows/columns (+ overscan) are rendered (a 100,000-row sheet renders ~280-360
  cells). Cells arrive in 100 x 26 blocks (`BlockCache`): de-duplicated, nearest-first, max 4 in flight, aborted
  when scrolled away, LRU-bounded, failed blocks retried after 3 s. Requests never exceed the 1000 x 100 cap.
- **Excel-sized sheets**: the scroll proxy is capped at 10,000,000 px and scrolled with a scale factor
  (Firefox 160 lays out 10 M px but not 30 M px: measured). Verified in a real browser on 1,048,000 rows.
- **RTL**: the *sheet's* direction (`SheetMeta.rtl`), not the UI language, decides column order and arrows:
  in an RTL sheet column A is at the right and ArrowLeft goes to the next column; Tab/Enter follow reading order.
  Layout uses logical positions (`inset-inline-start`), RTL `scrollLeft` (<= 0) is handled.
- Keyboard (arrows, Shift+arrows, Home/End, Ctrl+Home/End, PageUp/Down, Tab, Enter), click and drag selection,
  ARIA grid roles (`aria-rowcount/colcount`, `aria-activedescendant`, rows/columnheaders).
- Raw values only: numbers use the chosen digit set, strings are bidi-isolated, booleans localized. **Styles and
  number formats are not applied** (no contract exposes them yet).

**Real-browser measurements** (headless Firefox 160, 1 CPU / 4 GB / software rendering, real nginx + API (stub
engine) + PostgreSQL; scripts in `e2e/`, not asserted by CI):

| Check | Result |
|---|---|
| 100,000 x 20 sheet, first data cell after navigation | 0.33 s |
| rendered cells (initial / after jumping to the middle / to the bottom) | 279 / 360 / 279 |
| jump to the middle / bottom until populated | 0.19 s / 0.34 s |
| continuous scroll, ~2000 rows in 4 s | frame p50 33 ms, p95 50 ms, max 84 ms; 12 of 133 frames > 50 ms; 19 `/cells` requests; no cell left unloaded after settling |
| 1,048,000 rows | scroller height accepted (10,000,028 px); 0/25/50/75/100 % show the right rows; last row reachable; frame p95 50 ms |
| RTL layout and keys (4-column RTL sheet) | A right of B, row headers at the right edge, ArrowLeft = next column, ArrowRight = previous, Tab next, Home/End |
A screenshot of the RTL grid is in `e2e/screenshots/`. These are measurements on one slow machine, not budgets.
Frame times are dominated by React re-rendering ~300 cells per scroll step; they are fine here but have not been
tuned, and 60 fps is **not** claimed.

### Import UI and workbook shell (PR 8, docs/UX_SPEC.md F1)
- Workspace page `/workspaces/<id>`: drop zone (+ file chooser), file list, one card per import. Upload uses XHR
  (progress, cancel, CSRF); `.xls` and files over 100 MB are refused **before** sending; the job is polled (0.5 s -> 2 s),
  "this may take a minute" after 5 s, remembered by job id so polling resumes after a reload; done -> "Opened" or
  "Opened. N items need your attention" (items not fully supported) with Open / See report.
- Failures give plain Persian advice, never a code: legacy `.xls`, encrypted, strict OOXML, macro extension, stub-only CSV,
  too large, network; the "too large to undo -> convert to a Data Table" message (F4) is the exact spec sentence.
- Compatibility report panel: groups unsupported / partial / supported, per item the code, location, "kept in file",
  "editable"; the engine's English text is shown as given and labelled as such.
- Workbook shell regions: top bar, formula bar (address + raw value, editable), grid, side-panel host (report), sheet tabs, status bar
  (count/sum/average of the selection, flagged "loaded cells only" when not everything is loaded).
- 152 vitest tests pass; tsc strict and eslint clean.

### Cell editing and undo/redo (slice 3)
- Start editing by typing (replaces the content), F2 or double click (keeps it), or in the value bar above the grid. Enter saves and
  moves down, Tab saves and moves right, Escape cancels, clicking elsewhere saves. A text that is unchanged sends nothing.
- Delete/Backspace clears the selected range (one undo step, at most 50,000 cells). Ctrl+Z undoes; Ctrl+Y or Ctrl+Shift+Z redoes
  (by physical key, so it works on a Persian layout). The toolbar buttons do the same and are enabled from the real history.
- What is typed becomes: `=...` formula; `'text` text (apostrophe dropped); TRUE/FALSE boolean; a number (Persian/Arabic digits and
  separators accepted, sent as Latin); anything else text. Dates, percentages and currencies are NOT recognized yet: they stay text.
- `grid/editing.ts` (`WorkbookEditor`): one per open workbook; requests are serialized, each sends the previous entry's seq as
  `base_seq`; the returned `cells` and `others` are written into the block cache of the sheet they belong to (caches are kept per
  sheet while the workbook is open). A change that arrives while a block is still loading is applied when the block lands.
  On `version_conflict` the history and caches are reloaded and the error is shown. The save indicator shows saving / saved / not saved.
- Known limits: the first keystroke of an IME composition (`key` = "Process") cannot open the editor; use F2 or double click.
  The screen updates when the server answers (no optimistic display). Editing a date cell and saving without changes is a no-op, but
  changing it makes text. Copy/paste, fill handle and the history panel are not built. Not run in a real browser or on the real engine.

### Not done in this PR (the integrated slice is NOT complete in the UI)
- **No history panel, conflict banner** in the web app. Find is disabled. Cancelling a running import is impossible (no API; the card says so).
- Not verified in a real browser: upload via the file chooser/drag and drop, progress, the new shell layout. Real-browser e2e of
  upload -> edit -> undo on the REAL engine has not been written or run.
- Task bar, Data Tables, charts, tools, export, keyboard help, accessibility audit: not started.

### What does not work yet
- No history panel, operations, tables, charts (later PRs). Frozen panes, column resize, copy/paste, fill handle are not built.
- Screen-reader behaviour of the grid was not tested with a screen reader; row headers are `aria-hidden`.
- Unit/component tests run in jsdom; real-browser checks exist only as the manual `e2e/` scripts (Firefox only; Chrome and Safari were not tested). CSP with the production bundle and font loading were seen working in the native-stack run, not in CI.
- Display preferences are not stored on the server.

## Development
```bash
npm ci
npm run dev     # http://localhost:5173, proxies /api to http://localhost:8000
npm run check
```
