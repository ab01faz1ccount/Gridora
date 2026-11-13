# Gridora

A self-hosted, browser-based spreadsheet and data platform. The goal: give people who are not comfortable with complex software access to powerful Excel-style capabilities through graphical controls, while keeping advanced operations available.

> **Status: Phases 1–2 prepared (architecture, contracts, agent briefs).** There is no runnable application yet. This README only claims what exists.

**UI language:** Persian-first with RTL from day one. **Accounts:** local. **Upload limit:** 100 MB.

## Principles

- Runs inside your own network. No external services, no AI features, no data leaves the server.
- Honest about Excel compatibility: nothing is called "supported" until it is verified, and unsupported content is reported, never silently dropped.
- Workbooks (sheets) and structured Data Tables are both first-class, and data can move between them.
- Every change is a recorded operation: undo/redo, history, and reusable workflows come from the same mechanism.

## Phase READMEs

| Phase | Document | State |
|---|---|---|
| 1 — Architecture & contracts | [docs/phases/PHASE-1.md](docs/phases/PHASE-1.md) | Done (documents) |
| 2 — Agent plans & engine spike | [docs/phases/PHASE-2.md](docs/phases/PHASE-2.md) | Ready to start |
| 3 — Build & integrate | [docs/phases/PHASE-3.md](docs/phases/PHASE-3.md) | Planned |
| 4 — Harden & ship | [docs/phases/PHASE-4.md](docs/phases/PHASE-4.md) | Planned |

## For the agents

Start at [agents/README.md](agents/README.md), then your own brief and [docs/WORKFLOW.md](docs/WORKFLOW.md). Shared types live in [contracts/](contracts/).

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Requirements](docs/PRODUCT_REQUIREMENTS.md) · [Data model](docs/DATA_MODEL.md) · [API contracts](docs/API_CONTRACTS.md) · [Module boundaries](docs/MODULE_BOUNDARIES.md) · [Integration plan & status](docs/INTEGRATION_PLAN.md) · [Compatibility](docs/COMPATIBILITY_STRATEGY.md) · [Security](docs/SECURITY_MODEL.md) · [Testing](docs/TESTING_STRATEGY.md) · [Decisions](docs/DECISIONS.md) · [Workflow](docs/WORKFLOW.md) · [Review checklist](docs/REVIEW_CHECKLIST.md) · [Persian/RTL spec](docs/I18N_SPEC.md) · [Operations catalog](docs/OPERATIONS_CATALOG.md) · [Engine spike plan](docs/ENGINE_SPIKE_PLAN.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
