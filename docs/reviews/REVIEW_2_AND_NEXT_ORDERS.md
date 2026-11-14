# Review 2 — merged work (main at 2f8021c) and next orders

Reviewer: Agent 0. Date: 2026-11-14.

## What I checked, and how

| Check | Result |
|---|---|
| Folder ownership (every commit by Agent 1/2/3 against its allowed folders) | **Clean.** No agent touched files outside its folders. |
| Forbidden imports (`engine` -> `dataops`/`apps`, `dataops` -> `engine`/`apps`) | **Clean.** |
| `contracts/` edited by anyone but Agent 0 | **No.** |
| Conflict markers, duplicate files after the integration merge (PR #22) | **None found.** |
| Secrets or key files committed | **None.** |
| Engine: contract + engine tests, `mypy --strict` | **Pass** (64 engine tests, 13 contract tests). |
| Dataops, API, web tests | **Not run by me** (no network in my sandbox, so `polars`, `fastapi`, Postgres and npm packages are missing). Their results are the agents' claims until CI runs. Static review only. |
| README claims vs reality | Engine README: accurate and honest. API and web READMEs: consistent with the plans and clear about stubs. **Dataops README contradicts itself** (see O2.1). |

## Findings

1. **CI has never run.** The three agents proposed workflows; I reviewed and committed them (`.github/workflows/engine.yml`, `dataops.yml`, `apps-api.yml`, `apps-web.yml`, with `permissions: contents: read` and push-to-main triggers added). The first run may fail for environment reasons; fixing that is the first task of each agent.
2. **`deploy/` is still empty.** Phase 2 review C3.3 asked for `docker compose up` early. Not done.
3. **Agent 1 is only at E1.** CSV works; XLSX import/export, edits, deltas and formulas do not exist. This is the critical path for the Definition of Success.
4. **Status table and third-party notices were stale.** I updated both. Licenses are recorded from upstream knowledge and still need a machine scan.
5. **ADR-003 is half decided; ADR-012 (Polars-only) and ADR-013 (contract v0.3.0) are new.** See `docs/DECISIONS.md`.
6. **Contract v0.3.0:** `export_csv` now returns a `CompatibilityReport` (CC-9).

## Orders (paste each to the right agent)

### Agent 1 — engine
1. Rebase on main. Implement contract v0.3.0: `export_csv` returns a `CompatibilityReport`; keep or remove `last_export_report` as you prefer, but remove it from the README claims if removed.
2. Make the committed `engine.yml` workflow pass. Fix whatever the first CI run shows. Do not edit `.github/`; tell Agent 0 what to change.
3. Do **E3** (hostile-safe zip and XML, package model, byte-equal no-op round trip) then **E4** (XLSX read, compatibility registry, import report), in that order, as separate small PRs.
4. At E4, measure XLSX open time and memory at 100k x 20 with a **lazy row-window** reader and write the numbers in `BENCHMARKS.md`. If the eager path is needed anywhere, say so plainly.
5. Then **E5** (value edits, deltas with recalculated dependents, undo/redo, the replay-determinism test from C1.3 and the 200,000-cell cap).
6. Do **not** start E7 (formulas). Work on the open items of SPIKE_REPORT 1.4 only as far as your environment allows, and list what you cannot do. ADR-003 part 2 stays pending.
7. Every PR: tests, README "what works / what doesn't", honest limits.

### Agent 2 — dataops (after the usage limit resets)
1. Rebase on main; make `dataops.yml` pass.
2. **Fix the README** (O2.1): remove the stale lines saying `run_pipeline`, `bind_tool`, `validate_tool` and `chart_data` raise `not_implemented`, and the "Persian modules: M3/M5" line, so the file agrees with the "What works" list. Re-read the whole "does not work" list against the code.
3. Finish **M5 benchmarks**: 100k rows x 20 columns through the public executor for every operation, on a data table and on a sheet range backed by the fake `ExecContext`; `BENCHMARKS.md` with the exact command, commit, versions and hardware. Report misses; do not hide them.
4. Join as a pipeline step stays out of v1 (no contract change). Keep it listed as a limitation.
5. Add a contract-conformance test against `contracts/` v0.3.0 (it should already pass; `export_csv` does not concern you).
6. Do not add `duckdb` (ADR-012).

### Agent 3 — platform
1. Rebase on main; make `apps-api.yml` and `apps-web.yml` pass. Update the stub engine for v0.3.0 (`export_csv` returns a report).
2. **PR 11 `deploy-stack` next** (before PR 8): `docker compose up` with nginx, api, postgres, backup, `.env.example`, healthchecks, TLS notes, backup/restore scripts. Verify it starts with the **stub** engine and no outbound network. Say what you could and could not run in your environment.
3. Then **PR 7 `web-grid`** (virtualized grid, `BlockCache`, selection, keyboard in LTR and RTL, 100k-row benchmark) and **PR 8 `web-import`** (upload, job polling, compatibility panel). This gives the first slice: **CSV upload to grid, with the real engine**.
4. **PR 9** (history, undo/redo, optimistic edits) depends on Agent 1's E5. Build it against the stub first; switch to the real engine when E5 merges.
5. Keep the single-worker and in-memory working-copy limitation in the README.

## Integration check I will run next
When PR 7 and Agent 1's E1 are merged: CSV upload -> job -> open -> grid window, real engine, in a browser (Playwright). Until then the status table says "Integrated: stub only".

## Needed from the owner
- Real Excel-made workbooks (pivot, chart, VBA, conditional formats, Persian RTL, structured references), anonymized if sensitive. Required before ADR-003 part 2.
- **Rotate the GitHub App private key** (it was pasted into the chat). The session did not use it and it was not committed.
