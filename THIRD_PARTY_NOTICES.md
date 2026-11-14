# Third-Party Notices

No third-party code has been copied into Gridora yet.

## Rules

1. Check the license of any project **before** copying or adapting code.
2. Record every reuse in the provenance table below before merging.
3. Preserve required copyright and license notices.
4. Reimplementing an idea independently needs no notice but should be noted in the provenance table as "idea only".

## Provenance record

| Date | Source project | Version/commit | License | What was used | Where in Gridora | Reuse type (copied / adapted / ported / idea only) |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |

## Candidates under research (not dependencies)

| Project | License reported by its README/registry | Status |
|---|---|---|
| GridCraft | Apache-2.0 / MIT (to be verified in repo) | Research only; bundled assets and branding have separate terms |
| Gridline | MIT OR Apache-2.0 (crate metadata) | Research only |
| IronCalc | MIT OR Apache-2.0 (README) | Research only; spike planned |

## Dependencies in use (recorded by Agent 0 after the Phase 2 merges)

Licenses below are the upstream licenses as I know them. **They have not yet been machine-verified against the installed package metadata**; a license scan in CI (`pip-licenses`, `license-checker`) is required before Phase 4 and will replace this note.

| Component | Used by | License (upstream) | Notes |
|---|---|---|---|
| pydantic | contracts, engine, api | MIT | |
| polars | dataops | MIT | DuckDB was evaluated and **not** adopted (ADR-012) |
| fastapi, pydantic-settings | api | MIT | |
| uvicorn | api | BSD-3-Clause | |
| SQLAlchemy, Alembic | api | MIT | |
| asyncpg | api | Apache-2.0 | |
| argon2-cffi | api | MIT | |
| python-multipart | api | Apache-2.0 | |
| React, react-dom | web | MIT | |
| @tanstack/react-query | web | MIT | |
| zustand | web | MIT | |
| Vazirmatn font | web | SIL OFL 1.1 | Bundled with its license at `apps/web/public/fonts/OFL.txt`; the font must not be sold on its own |
| Vite, Vitest, TypeScript, ESLint, Testing Library, jsdom | web (dev) | MIT / Apache-2.0 / BSD | dev-only, not shipped |
| pytest, ruff, mypy, jsonschema | all Python (dev) | MIT | dev-only |
| hypothesis | dataops (dev) | MPL-2.0 | dev-only; not shipped or modified |
| PostgreSQL | deployment | PostgreSQL License | server, not linked |

Copied or adapted external code: **none** (confirmed from the engine spike report section 6 and the agents' PR notes).
Apache ECharts is planned for the chart UI and will be added here when it lands.
