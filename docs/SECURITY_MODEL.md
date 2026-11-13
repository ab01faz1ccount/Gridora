# Gridora — Security Model

## Assets

User workbooks and tables (potentially sensitive), credentials, the server file system.

## Principles

Self-hosted, no outbound data flows, least privilege, all uploads hostile.

## Controls

**Authentication/session:** argon2id hashes; server-side sessions; HttpOnly + Secure + SameSite cookies; CSRF token on mutating requests; login rate limiting.

**Authorization / isolation:** every resource has `owner_id`; every query is filtered by the session user; other users' resources return `404`. Admin role cannot read user files via the API. Isolation tests are mandatory in CI.

**File storage:** UUID-addressed files, paths never returned; no user-controlled path components; originals immutable; atomic writes (temp file + fsync + rename).

**Untrusted parsing (XLSX/CSV):**
- Upload size cap; decompressed-size and compression-ratio caps; entry-count cap; reject path traversal in zip entries.
- XML parsed with external entities and DTDs disabled (e.g. defusedxml-class behavior in Python; equivalent in any native code).
- Sheet dimension and cell-count caps; timeouts; imports run in a job with memory limits.
- v1 (Phase 3): import runs in a worker thread with the engine's budgeted limits and a timeout. OS-level isolation (separate process with RLIMIT) is a **Phase 4** target because a `WorkbookHandle` cannot cross processes; it requires an engine snapshot format (ADR-011). Until then this is a documented limitation.
- VBA/macros and embedded objects are preserved as opaque data and **never executed**.

**Formula safety:** no network, file, or shell functions; external workbook links not followed.

**Transport:** TLS at Nginx (internal CA or provided certificates); security headers; strict CSP for the web app.

**API hygiene:** schema validation on all input; consistent error envelope without stack traces; request IDs; audit log of logins, uploads, deletes, exports.

**Supply chain:** pinned lockfiles, license check in CI, dependency review recorded in DECISIONS.md.

**Backups:** encrypted at rest if the host provides disk encryption; backup access limited to admins.

## Known gaps (to be closed in later phases)

Malware scanning of uploads, SSO, per-field encryption, sharing between users (not offered in v1).
