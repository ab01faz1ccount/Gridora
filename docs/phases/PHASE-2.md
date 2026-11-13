# Phase 2 — Agent Plans & Engine Spike

**Status:** Ready to start once the repository is pushed. **No product features are implemented in this phase either.**

## Goal
Get three specialist agents to produce reviewed plans, run the engine spike, and settle every open design question before large-scale coding starts.

## What exists at the start of this phase
- Architecture, data model, API contracts, security and compatibility strategy (Phase 1).
- Machine-readable contracts in `contracts/` (Python pydantic + TypeScript). Python contract tests: 8 passing; the TypeScript file type-checks under `--strict`. These only prove the types are self-consistent, not that any module implements them.
- Agent briefs in `agents/`, working agreement (`docs/WORKFLOW.md`), review checklist, i18n spec, operations catalog, engine spike plan.

## What the agents do in this phase

| Agent | Output | Reviewed by |
|---|---|---|
| Agent 1 | `packages/engine/PLAN.md`, then `SPIKE_REPORT.md` (see `docs/ENGINE_SPIKE_PLAN.md`) | Agent 0 → ADR-003 |
| Agent 2 | `packages/dataops/PLAN.md` | Agent 0 |
| Agent 3 | `apps/PLAN.md` | Agent 0 |

No implementation PRs are accepted until the agent's plan is approved.

## Exit criteria
- All three plans approved, or revised and re-approved.
- ADR-003 (engine strategy) moved from Proposed to Accepted with evidence.
- Contract gaps found by the agents resolved (`CONTRACT_CHANGE` notes merged).
- Any new dependency recorded in DECISIONS.md and THIRD_PARTY_NOTICES.md.

## Things Agent 0 will check in the plans
- Do they respect module boundaries and the "must not modify" lists?
- Is Persian-first/RTL handled structurally, not as an afterthought?
- Is the 100k-row path designed (windowing, Polars, Parquet), with a measurement plan?
- Do they promise only what they can verify?

## Limitations
Still documentation and contracts only. Library facts in the spike plan are unverified until Agent 1 reports.
