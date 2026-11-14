# apps/api — Gridora HTTP API and composition layer

Owner: Agent 3. Plan: [`../PLAN.md`](../PLAN.md). Contracts: `../../contracts/` (v0.2.0, read-only).

## Status: In progress (PR 1 skeleton, PR 2 auth, PR 3 workspaces/files)

### What works (each item has a test)
- App factory (`gridora_api.main:create_app`), configuration from `GRIDORA_*` environment variables.
- Standard success envelope and error envelope; every response carries `X-Request-ID`.
- One status table for the 13 contract error codes, checked against `gridora_contracts.ERROR_CODES`.
- Request-validation errors return `400 validation_failed` with JSON-pointer paths (not FastAPI's 422).
- Unhandled exceptions return `500 internal_error` with no stack trace or exception text.
- `/healthz` and `/readyz` (outside `/api/v1`, not part of the contract).
- Contract route conformance: routes in the app must be a subset of the route table parsed from
  `docs/API_CONTRACTS.md` (+ the v0.2 additions); the number still unimplemented is reported.

- Auth (PR 2): `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` returning contract `AuthResult`.
  argon2id hashes; server-side sessions (only SHA-256 of the cookie token stored); HttpOnly,
  Secure, SameSite=Strict cookie (`__Host-` prefix); session rotated at login; idle (sliding) and
  absolute expiry; synchronizer CSRF token checked on every mutating route that uses the `auth`
  dependency; Postgres-backed login rate limit (`429` + `Retry-After`); audit log rows for login
  and logout; operator CLI (`python -m gridora_api.cli create-user | reset-password | check-config`);
  optional first-start bootstrap admin from env.
- Alembic migration `0001` (users, sessions, login_attempts, audit_log); a test fails if models and
  migrations diverge.
- Isolation harness: every `/api/v1` route with an id parameter must have an isolation case
  (registry is empty until PR 3 adds owned resources).

- Workspaces and files (PR 3): workspace CRUD (delete needs `?confirm=true`, removes rows and
  stored bytes), file list, streaming multipart upload, download. Owner-scoped repositories
  (`db/repos/owned.py`: no fetch-by-id-alone exists; another user's id is `404`, same as missing).
- Upload: streamed to quarantine, never buffered; `file_too_large` the moment the file part
  passes the cap (exactly 100 MiB passes, +1 byte fails; tested at the real default with a streamed
  body); early reject on a large `Content-Length`; extension allowlist (`.xlsx .xlsm .csv`) plus
  magic-byte check (`415`); truncated or multi-file bodies are `400` and leave nothing behind;
  display names are sanitized and never used in paths.
- Storage: only `storage/layout.py` builds paths (UUID components + allowlists); files are `0600`,
  placed by temp+fsync+rename and never overwritten; `PathResolver` for dataops is implemented there.
- Isolation: the OpenAPI-driven harness now covers all 6 id routes (404 for another user, 401
  without a session, nothing changed). A test client scans every JSON body and every header of
  every response in the suite and fails the test on any server path or storage detail.

### What does not work yet
- No jobs, workbooks, engine or operations. `POST .../files` returns `job_id: null` until the
  import job exists (PR 5). The file is stored but not parsed or validated beyond type/magic.
- Lists are not paginated (capped at 1000 rows).
- Only `.xlsx`, `.xlsm`, `.csv` are accepted; UTF-16 CSV is refused (needs a NUL-free text file).
- Rate limiting counts per username and per IP; behind nginx set `GRIDORA_TRUST_PROXY_HEADERS=true`.
- `POST /auth/logout` returns `204` with no body (the contract does not define a response).
- Admin role exists but nothing uses it yet; there are no HTTP admin endpoints (Agent 0 decision).
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
# tests need PostgreSQL: GRIDORA_TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host/db_test
GRIDORA_DATA_ROOT=./data uvicorn --factory gridora_api.main:run --reload
```
