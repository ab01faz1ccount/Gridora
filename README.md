# Gridora

A self-hosted, browser-based spreadsheet and data platform for people who want the power of Excel without its complexity. It runs entirely inside your own network: no external services, no AI features, nothing leaves the server.

The interface is Persian-first and right-to-left, with Jalali calendar support, Persian and Arabic-Indic digits, and Persian-aware sorting and text cleaning. English works too.

## What you can do

- **Open and edit workbooks.** Upload `.xlsx`, `.xlsm` or `.csv` (up to 100 MB). A virtualized grid keeps 100,000+ rows fast; edits are saved as you go, with unlimited undo and redo and a readable history.
- **Use formulas.** About 400 functions, dynamic arrays (`FILTER`, `SORT`, `UNIQUE`, `SEQUENCE` and friends that spill into neighbouring cells), Excel number formats, and a calendar mode (Jalali by default, Gregorian or Hijri on request).
- **Clean and analyse data with buttons, not formulas.** Sort, filter, remove duplicates, find and replace, fill, clean text (including Persian/Arabic letter and digit normalisation), split and merge columns, change types, computed columns, group and total, pivot, unpivot, join, calendar conversion. Every operation shows a preview and what it will change before you apply it, and can be undone.
- **Work with Data Tables.** Large, tidy tables stored as versioned Parquet, kept separate from sheets but connected to them. Every change is a new version you can go back to.
- **Make charts** (bar, line, pie, scatter, area) from a sheet range or a Data Table.
- **Reuse your work.** Save a sequence of operations as a tool with named inputs, and run it again on other data.
- **Export** to `.xlsx` or `.csv`, with a report of anything that could not be carried over.

Every capability above is available through the HTTP API. Which of them already have a screen in the web interface is listed in the [roadmap](docs/ROADMAP.md).

## Excel compatibility

Gridora reads and writes standard Excel files and keeps what it does not understand (pivot tables, charts, macros, conditional formats and more) byte for byte instead of dropping it. Every import and export produces a compatibility report listing what was preserved, what is editable and what is not. Gridora does not claim full Excel compatibility; the tested behaviour is what [the compatibility strategy](docs/COMPATIBILITY_STRATEGY.md), the report and the [test corpus](corpus/README.md) show. VBA is preserved and never run.

## Install

You need Docker with Compose.

```bash
cd deploy
cp .env.example .env            # set POSTGRES_PASSWORD (letters and digits) and the first admin
./scripts/make-dev-cert.sh      # self-signed certificate for a trial; see deploy/TLS.md for real ones
docker compose up -d --build
docker compose ps               # wait until api, nginx and postgres are healthy
```

Open `https://localhost`, sign in with the admin from `.env`, then remove the bootstrap variables from `.env` and run `docker compose up -d` again. More users: `docker compose exec api python -m gridora_api.cli create-user --username NAME --password-stdin`. Backups, restore, upgrades and logs: [deploy/RUNBOOK.md](deploy/RUNBOOK.md).

## How it is built

One FastAPI process imports two Python packages through typed interfaces; a React + TypeScript app talks to it over REST; PostgreSQL holds accounts, metadata and history; files and Data Table versions live on disk. Nginx terminates TLS.

| Part | Folder | Role |
|---|---|---|
| Workbook engine | [packages/engine](packages/engine) | Cell model, XLSX/CSV import and export, formulas, edits and undo deltas, compatibility report |
| Data operations | [packages/dataops](packages/dataops) | Operations, pipelines, tools, Data Tables, chart data, Persian text and calendar handling |
| API | [apps/api](apps/api) | Accounts, workspaces, jobs, history, composition of the two packages |
| Web app | [apps/web](apps/web) | Persian-first RTL interface |
| Contracts | [contracts](contracts) | The shared types and interfaces every module obeys |
| Deployment | [deploy](deploy) | Docker Compose: nginx, api, postgres, backup |
| Test corpus | [corpus](corpus) | Real-world and hostile workbooks with a manifest |

Uploads are treated as hostile: files are validated before parsing, parsed with size, ratio and depth limits, never extracted to disk and never executed.

## Documentation

- [Project reference](docs/REFERENCE.md) — what every module does, in detail
- [Roadmap](docs/ROADMAP.md) — status and what remains
- [Architecture](docs/ARCHITECTURE.md) · [Data model](docs/DATA_MODEL.md) · [API contracts](docs/API_CONTRACTS.md) · [Module boundaries](docs/MODULE_BOUNDARIES.md)
- [Compatibility](docs/COMPATIBILITY_STRATEGY.md) · [Security](docs/SECURITY_MODEL.md) · [Limits and measured performance](docs/LIMITS.md)
- [UX specification](docs/UX_SPEC.md) · [Persian/RTL specification](docs/I18N_SPEC.md) · [Operations catalog](docs/OPERATIONS_CATALOG.md)
- [Decisions](docs/DECISIONS.md) · [Testing](docs/TESTING_STRATEGY.md) · [Contributing](docs/CONTRIBUTING.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
