# Contributing

## Working rules
- One concern per pull request, on a feature branch; `main` is protected by CI. Tests, lint and types must pass (`pytest`, `ruff check .`, `mypy`, `npm run check`, run from each module's folder).
- Module boundaries ([MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)): `engine` and `dataops` never import each other and never import `apps/*`; only `apps/api` wires them, through the four factory functions in `contracts/`.
- `contracts/` defines everything that crosses a module boundary. Change it deliberately: both language files, the docs, an ADR for anything non-additive.
- Tool versions are pinned (`ruff`, `mypy`, `pytest`); bump them in a PR of their own.
- CI workflows live in `.github/workflows/`; there is one per module plus `deploy-stack` (builds and exercises the whole Docker stack).

## Dependencies and copied code
- A new dependency needs a line in [DECISIONS.md](DECISIONS.md) (why, alternatives) and in [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) with its licence. No runtime service outside the stack, no outbound network calls, no AI features.
- Never copy code before its licence is checked and recorded. When in doubt, reimplement the idea independently.

## Honesty rules
- Never write "supported" for something a test does not prove. Excel compatibility is described only by what the compatibility report and the corpus tests show.
- Anything that is not carried over is reported to the user and, where possible, preserved byte for byte. Nothing is dropped silently.
- Measured numbers go in `BENCHMARKS.md` / [LIMITS.md](LIMITS.md) with the command that produced them.

## Review checklist
**Contracts and boundaries:** wire types match `contracts/`; no forbidden imports; no duplicate implementation of something another module owns.
**Correctness:** tests cover the happy path, edge cases and failures, and fail if the feature is removed; undo/redo restores state exactly; error codes come from `ERROR_CODES` and use the standard envelope.
**Security:** inputs validated; uploads treated as hostile; owner scoping on every query (another user's id is `404`); no paths or stack traces in responses; no outbound calls with user data.
**Compatibility:** unsupported items reported and preserved where possible; no claim of full Excel compatibility.
**Persian first:** strings in the i18n catalog; RTL layout works; digits and dates per [I18N_SPEC.md](I18N_SPEC.md).
**Performance:** the 100,000-row scenario is measured, not guessed.
**Docs:** [REFERENCE.md](REFERENCE.md) and [ROADMAP.md](ROADMAP.md) match the change; limits listed plainly.

## Test corpus
`corpus/` holds real-world and hostile OOXML files with a manifest (see its README). Put your own files in `corpus/private/` (ignored by git); tests skip what is absent.
