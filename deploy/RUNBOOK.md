# Runbook

## First start
1. `cp .env.example .env`, set `POSTGRES_PASSWORD` (letters/digits), the bootstrap admin, `chmod 600 .env`.
2. Put the certificate in `certs/` (TLS.md).
3. `docker compose up -d --build`; wait for `healthy`.
4. Run `scripts/smoke.sh`. Remove `GRIDORA_BOOTSTRAP_ADMIN_*` from `.env`; `docker compose up -d`.
5. More users: `docker compose exec api python -m gridora_api.cli create-user --username NAME --password-stdin`
   (add `--admin` for an admin; `reset-password` likewise). There are no HTTP admin endpoints.

## Logs and health
- `docker compose logs -f api nginx`. The same request id (`X-Request-ID`) appears in nginx and API logs and in every error response.
- `docker compose ps` shows health. The API readiness detail: `docker compose exec api python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/readyz').read())"`.

## Backup
- Automatic: daily at `BACKUP_AT` (UTC), keep `BACKUP_KEEP_DAYS`. Manual: `docker compose exec backup backup.sh`.
- Layout in the `backups` volume: `db/gridora-<stamp>.dump`, `files/<stamp>/` (hard-linked snapshot), `MANIFEST-<stamp>.txt`.
- **Move backups off this host.** Replace the `backups` volume in `docker-compose.yml` by a bind mount (`/mnt/other-disk/gridora-backups:/backups`) or copy the folder elsewhere on a schedule.

## Restore (replaces the database)
```bash
docker compose stop nginx api
docker compose run --rm --no-deps backup restore.sh --yes /backups/db/gridora-<stamp>.dump /backups/files/<stamp>
docker compose up -d
```
The script verifies the dump's checksum, restores, copies files in additively, and lists any file the database
references but is missing on disk (exit code 4). Then run `scripts/smoke.sh`.
**Practice a restore on a copy before you need it**; it has been tested only on a scratch database (README.md).

## Upgrade
`git pull && docker compose up -d --build`. Migrations run at API start. Take a backup first. Downgrades are not supported.

## Limits to know
Single API process; open workbooks are kept in memory (default cap 8, `GRIDORA_MAX_OPEN_WORKBOOKS`); the stub engine reads CSV only.
