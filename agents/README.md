# agents/

Briefs for the three specialist agents. Give each agent its own file plus `docs/WORKFLOW.md`.

| Agent | Brief | Folders it may change |
|---|---|---|
| Agent 1 — Workbook Engine & Compatibility | [AGENT_1_ENGINE.md](AGENT_1_ENGINE.md) | `packages/engine/` |
| Agent 2 — Data Operations & Analytics | [AGENT_2_DATAOPS.md](AGENT_2_DATAOPS.md) | `packages/dataops/` |
| Agent 3 — Frontend, Backend & Platform | [AGENT_3_PLATFORM.md](AGENT_3_PLATFORM.md) | `apps/`, `deploy/` |

Agent 0 (lead architect) owns `contracts/`, `docs/`, `agents/`, root files and all merge decisions.

Every agent starts with a plan PR (Step 0) and waits for approval before coding.
