# Phase 4 — Harden & Ship

**Status:** Planned. Completed by Agent 0 after Phase 3, with verified facts only.

## Goal
A stack an admin can install on an internal server and rely on, with an honest list of limits.

## Work
- `docker compose up` on a clean machine; offline runtime verified (no outbound calls).
- Backup and restore scripts exercised end to end (restore drill documented).
- TLS setup guide for an internal CA or provided certificates.
- Security pass against `docs/SECURITY_MODEL.md`: isolation, CSRF, upload limits, hostile files, resource limits for the import worker.
- Compatibility pass: run the fixture corpus, publish the supported / partial / preserved / unsupported table generated from tests.
- Performance pass at 100k rows, numbers published.
- Admin guide, user guide (Persian first), upgrade notes.

## Documentation deliverables
`docs/ADMIN_GUIDE.md`, `docs/USER_GUIDE.fa.md`, `docs/KNOWN_LIMITATIONS.md`, final `docs/phases/PHASE-4.md`, updated root README with the real feature list.

## Exit criteria
- Fresh-machine install works from the docs alone.
- Restore drill succeeds.
- Known limitations and future work are written down plainly; no unverified compatibility claims.

## Future work (not in scope now)
More chart types, additional import/export formats, database connectors, SSO (LDAP/OIDC), sharing between users, user-defined operations, optional scripting.
