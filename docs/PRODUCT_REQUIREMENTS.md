# Gridora — Product Requirements

Status: Phase 1 draft.

## Vision

A self-hosted, browser-based spreadsheet and data platform that makes powerful Excel-style capabilities available to people who are not comfortable with complex software, without capping what advanced users can do.

It is a spreadsheet-centered data platform: not a dashboard builder, not a report generator, not a static XLSX viewer.

## Confirmed decisions (treated as requirements)

1. Long-term goal is full Excel compatibility. It is never claimed until verified.
2. Most calculations happen through graphical controls, not formulas. Formulas still work for those who want them.
3. Advanced operations remain available.
4. Target size: a few thousand up to ~100,000 rows per workbook.
5. Single-user editing per file; no real-time collaboration.
6. Each user has a private workspace and files.
7. Unsupported Excel features are detected and reported; content is preserved when technically possible.
8. Two data models: Workbook/Sheet and independent structured Data Tables, with import, transform, export, and linking between them.
9. History (undo/redo) and reusable operations/workflows.
10. No AI features in the initial scope.
11. Internal-server/self-hosted deployment; no sensitive data leaves the network; no third-party SaaS dependency.

## Personas

- **Novice:** wants "sum this column", "remove duplicates", "make a chart" with buttons and plain-language labels.
- **Power user:** pipelines, joins, pivots, reusable workflows, formulas.
- **Admin:** installs, backs up, manages users.

## Functional requirements for the first usable release (MVP)

| ID | Requirement | Phase target |
|---|---|---|
| FR-1 | Create and manage a user workspace | 3–4 |
| FR-2 | Import XLSX/CSV | 3 |
| FR-3 | Display and edit sheet data (virtualized grid) | 3 |
| FR-4 | Data operations via GUI (sort, filter, dedupe, find/replace, fill, group/aggregate, pivot, join, computed column) | 3 |
| FR-5 | Create and update a chart (ECharts) | 3 |
| FR-6 | Save and reopen (versioned, original preserved) | 3 |
| FR-7 | Undo/redo and operation history | 3 |
| FR-8 | Save reusable operations/workflows | 3 |
| FR-9 | Export XLSX/CSV | 3 |
| FR-10 | Compatibility report on import/export | 3 |
| FR-11 | Run in Docker behind Nginx | 4 |
| FR-12 | Workbook ↔ Data Table connect/import/export | 3 |

## Non-functional requirements

- Open a 100k-row workbook and render the first viewport quickly (target budget in TESTING_STRATEGY; not a claim).
- Never overwrite the original file.
- All parsing of uploads is treated as hostile (SECURITY_MODEL).
- Honest status: README and module table must distinguish working / partial / planned.

## Non-goals (now)

AI features, real-time co-editing, macros execution (VBA is preserved, never run), mobile app, SaaS hosting, speculative abstractions.

## Owner decisions (resolved)

1. UI is Persian-first with full RTL support from the start (i18n-ready for other languages; Jalali calendar/number-format handling to be scoped in Phase 2).
2. Local accounts only in v1; LDAP/OIDC deferred.
3. Maximum upload size: 100 MB.
