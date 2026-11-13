# Gridora — Working Agreement for Agents

## Branches and PRs
- Branch names: `agent1/<topic>`, `agent2/<topic>`, `agent3/<topic>`. Never push to `main`.
- Small PRs, one concern each. Each PR includes tests and updates the module docs.
- PR description template is in `.github/pull_request_template.md`. Fill every section.

## Order of work
1. Step 0: plan PR (`PLAN.md`) → Agent 0 review → approval.
2. Implementation PRs in the slice order of `docs/INTEGRATION_PLAN.md`.
3. Spike reports and dependency additions go through DECISIONS.md before merging.

## Contracts
`contracts/` is read-only for agents. If something is missing or wrong: add a `CONTRACT_CHANGE:` section to the PR describing it, keep working against the current version, and wait.

## Dependencies and copied code
- New dependency → note in PR (name, version, license, why, alternatives). Agent 0 records it in DECISIONS.md and THIRD_PARTY_NOTICES.md.
- Never copy code before its license is checked and recorded. Reimplement ideas independently when in doubt.

## Honesty rules
- Never write "supported" for something not tested.
- Update the status table in `docs/INTEGRATION_PLAN.md` truthfully (Planned / In progress / Implemented / Tested / Integrated).
- List known limitations in every PR and in the module README.

## Definition of done for a PR
Tests pass in CI, lint and types clean, docs updated, no cross-module imports against the rules, no new unreviewed dependency, limitations stated.

## Phase documentation
At the end of each phase, Agent 0 produces `docs/phases/PHASE-N.md`. Agents contribute a short "what works / what doesn't" section in their module README, which Agent 0 consolidates.
