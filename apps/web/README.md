# apps/web — Gridora web app

Owner: Agent 3. Plan: [`../PLAN.md`](../PLAN.md). Contracts: imported from `../../contracts/typescript`
through the `@contracts` alias (never copied).

## Status: In progress (PR 6 skeleton + PR 7 grid)

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

### What does not work yet
- No upload UI, import panel, editing, history, operations, tables, charts (later PRs); the grid is read-only and reached only by URL for now. Frozen panes, column resize, copy/paste, fill handle are not built.
- Screen-reader behaviour of the grid was not tested with a screen reader; row headers are `aria-hidden`.
- Unit/component tests run in jsdom; real-browser checks exist only as the manual `e2e/` scripts (Firefox only; Chrome and Safari were not tested). CSP with the production bundle and font loading were seen working in the native-stack run, not in CI.
- Display preferences are not stored on the server.

## Development
```bash
npm ci
npm run dev     # http://localhost:5173, proxies /api to http://localhost:8000
npm run check
```
