# Gridora — Agent 0 Review Checklist

Use for every PR. A PR that compiles but fails this list is not merged.

## Contracts & boundaries
- [ ] Types match `contracts/` exactly; no ad-hoc shapes on the wire.
- [ ] No import between `engine` and `dataops`; no module imports `apps/*`.
- [ ] No edits outside the agent's allowed folders.
- [ ] No duplicate implementation of something another module owns.

## Correctness
- [ ] Tests cover happy path, edge cases and failure paths; they fail if the feature is removed.
- [ ] Undo/redo restores state exactly (where applicable).
- [ ] Error codes come from `ERROR_CODES`; envelope is standard.

## Security
- [ ] Inputs validated; uploads treated as hostile.
- [ ] Owner scoping on every query; other users' data returns 404.
- [ ] No filesystem paths or stack traces in responses.
- [ ] No outbound network calls with user data; no AI features.

## Compatibility honesty
- [ ] Nothing is silently dropped; unsupported items are reported and preserved when possible.
- [ ] No claim of full Excel compatibility.

## Persian-first
- [ ] Strings in the i18n catalog; RTL layout works; digits/date handling per `docs/I18N_SPEC.md`.

## Dependencies & provenance
- [ ] New dependency justified and licensed; recorded in DECISIONS/THIRD_PARTY_NOTICES.
- [ ] Any copied code has a provenance entry.

## Performance
- [ ] 100k-row scenario measured, numbers in BENCHMARKS.md (not guessed).

## Docs
- [ ] Module README and status table updated; limitations listed honestly.
- [ ] Spot-check by running it, not only by reading it.
