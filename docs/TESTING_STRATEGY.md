# Gridora — Testing Strategy

## Layers

| Layer | Scope | Tooling (proposed) |
|---|---|---|
| Unit | engine, dataops, services | pytest; Vitest for web |
| Contract | every API response/request validates against `contracts/` schemas | schemathesis / jsonschema |
| Integration | API + Postgres + real engine + dataops | pytest with docker services |
| Compatibility | XLSX round-trip corpus | custom harness; LibreOffice headless as secondary oracle |
| Security | user isolation, CSRF, hostile files | pytest + crafted fixtures |
| Performance | 100k-row open/scroll/operate/save | scripted benchmarks |
| End-to-end | Definition-of-Success scenario in a browser | Playwright |

## Fixture corpus

Small hand-crafted XLSX files for each feature code in the compatibility registry, plus larger realistic files. Hostile set: zip bomb, XXE, path traversal entries, huge dimensions, corrupted parts.

## Performance budgets (targets to be validated, not claims)

- Open 100k rows × 20 columns: first viewport rendered in a few seconds on reference hardware.
- Sort/filter/dedupe at 100k rows: interactive (seconds, with progress for slower ops).
- Memory per open workbook measured and documented.
Reference hardware will be defined when the first benchmark runs.

## Definition-of-Success E2E scenario

Create workspace → import workbook → view/edit → run an operation → create chart → save → reopen → undo/redo → save tool → export → read compatibility report.

## CI gates

Lint + type check (ruff, mypy, tsc), unit, contract, isolation tests; license scan; build of Docker images.
