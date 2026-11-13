# apps/api — Gridora HTTP API and composition layer

Owner: Agent 3. Plan: [`../PLAN.md`](../PLAN.md). Contracts: `../../contracts/` (v0.2.0, read-only).

## Status: In progress (PR 1 of the plan: skeleton only)

### What works (each item has a test)
- App factory (`gridora_api.main:create_app`), configuration from `GRIDORA_*` environment variables.
- Standard success envelope and error envelope; every response carries `X-Request-ID`.
- One status table for the 13 contract error codes, checked against `gridora_contracts.ERROR_CODES`.
- Request-validation errors return `400 validation_failed` with JSON-pointer paths (not FastAPI's 422).
- Unhandled exceptions return `500 internal_error` with no stack trace or exception text.
- `/healthz` and `/readyz` (outside `/api/v1`, not part of the contract).
- Contract route conformance: routes in the app must be a subset of the route table parsed from
  `docs/API_CONTRACTS.md` (+ the v0.2 additions); the number still unimplemented is reported.

### What does not work yet
- **No `/api/v1` business route exists.** No database, no auth, no files, no engine, no jobs.
- `/readyz` checks only that the data directory is writable.
- The 405 response keeps status 405 with code `bad_request` (the contract has no 405 code).

### Known limitations (by design for v1, from the plan)
- Single API worker process (working copies will live in memory). No horizontal scaling.
- No OS-level isolation for hostile-file parsing in v1 (ADR-011); relies on engine limits. Phase 4.

## Development
```bash
pip install -e ../../contracts/python
pip install -e ".[dev]"
pytest
ruff check . && mypy src
GRIDORA_DATA_ROOT=./data uvicorn --factory gridora_api.main:run --reload
```
