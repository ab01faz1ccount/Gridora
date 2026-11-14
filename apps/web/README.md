# apps/web — Gridora web app

Owner: Agent 3. Plan: [`../PLAN.md`](../PLAN.md). Contracts: imported from `../../contracts/typescript`
through the `@contracts` alias (never copied).

## Status: In progress (PR 6: skeleton, sign-in, workspaces). No grid yet.

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

### What does not work yet
- No grid, upload, import, history, operations, tables, charts (later PRs).
- No browser (Playwright) tests yet: all tests run in jsdom, so layout, real RTL rendering, font
  loading and CSP are **not** verified. Jalali formatting depends on the browser's ICU data.
- Display preferences are not stored on the server.

## Development
```bash
npm ci
npm run dev     # http://localhost:5173, proxies /api to http://localhost:8000
npm run check
```
