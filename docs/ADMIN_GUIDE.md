# Administrator guide

For the person who installs and looks after a Gridora server. Details of each piece: [`deploy/README.md`](../deploy/README.md), [`deploy/RUNBOOK.md`](../deploy/RUNBOOK.md), [`deploy/TLS.md`](../deploy/TLS.md). Measured limits: [LIMITS.md](LIMITS.md).

## 1. Requirements
- A Linux, macOS or Windows machine with **Docker** and **Docker Compose v2**.
- Memory: plan for about 1 GB for the API plus the size of the workbooks open at once (a 100,000-row sheet needs a few hundred MB; see LIMITS.md). By default at most 8 workbooks are open at once (`GRIDORA_MAX_OPEN_WORKBOOKS`).
- Disk: the uploaded files, the database and the backups. Backups live on the same host unless you move them (section 6).
- Building the images needs internet access (PyPI, npm, image registries). Running the stack does not: the containers cannot reach the outside.

## 2. First installation
```bash
git clone <your copy of the repository> gridora && cd gridora/deploy
cp .env.example .env
chmod 600 .env
```
Edit `.env`:
- `POSTGRES_PASSWORD`: letters and digits only (it is placed in a URL).
- `GRIDORA_BOOTSTRAP_ADMIN_USERNAME` / `GRIDORA_BOOTSTRAP_ADMIN_PASSWORD`: the first administrator (password at least 10 characters).
- Optional: `HTTP_PORT`, `HTTPS_PORT`, `BACKUP_AT` (UTC time), `BACKUP_KEEP_DAYS`.

Certificate: for a trial run `./scripts/make-dev-cert.sh` (self-signed, browsers warn). For real use follow `deploy/TLS.md`.

Start:
```bash
docker compose up -d --build
docker compose ps          # wait until api, nginx and postgres say "healthy"
BASE_URL=https://localhost SMOKE_USER=admin SMOKE_PASSWORD='...' CURL_OPTS=-k ./scripts/smoke.sh
```
Then delete the two `GRIDORA_BOOTSTRAP_ADMIN_*` lines from `.env` and run `docker compose up -d` again. Open `https://<server>/` in a browser. The app works only over HTTPS (its cookies are `Secure`).

## 3. Users
There are no administration pages in the web app; users are managed from the command line:
```bash
docker compose exec api python -m gridora_api.cli create-user --username NAME --password-stdin          # add --admin for an administrator
docker compose exec api python -m gridora_api.cli reset-password --username NAME --password-stdin
```
Passwords are read from the prompt or standard input, never from arguments.

**Self-service sign-up.** The sign-in page lets anyone who can reach the server create a plain (non-admin) account and use it for their own work; accounts never see each other's files. Settings (environment, prefix `GRIDORA_`):

| Setting | Default | Meaning |
|---|---|---|
| `REGISTRATION_ENABLED` | `true` | `false` closes sign-up (then only the command line creates users) |
| `REGISTER_MAX_PER_IP` | `10` | sign-up attempts per IP per 15 minutes |
| `MAX_USERS` | `1000` | no more accounts after this many |
| `MAX_WORKSPACES_PER_USER` | `50` | workspaces one account may have |
| `USER_STORAGE_BYTES` | `2147483648` | total size of one account's files (admins are exempt from both quotas) |

A server that is open to the internet should keep these limits, or set `REGISTRATION_ENABLED=false` and add users by hand. Users change their own password on the Account page (it signs their other devices out); a forgotten password is reset with `reset-password` above.

## 4. Upgrade
1. Take a backup (section 6).
2. `git pull && docker compose up -d --build` (database migrations run when the API starts).
3. Run `scripts/smoke.sh`.
Downgrading is not supported: restore the backup instead.

## 5. Logs and health
- `docker compose logs -f api nginx`. Every request has an id (`X-Request-ID`) that appears in the nginx log, the API log and any error shown to the user: ask users for it when they report a problem.
- `docker compose ps` shows health.

## 6. Backup and restore
- A backup runs daily at `BACKUP_AT` and keeps `BACKUP_KEEP_DAYS` days. Manual backup: `docker compose exec backup backup.sh`.
- **Copy backups to another disk or machine.** Replace the `backups` volume in `docker-compose.yml` with a bind mount, or copy the folder on a schedule.
- Restore (replaces the database):
```bash
docker compose stop nginx api
docker compose run --rm --no-deps backup restore.sh --yes /backups/db/gridora-<stamp>.dump /backups/files/<stamp>
docker compose up -d
```
The script refuses a dump whose checksum does not match and lists files the database needs but the disk lacks (exit code 4).
- Practise a restore on a copy before you need it.

## 7. Security notes
- Only nginx publishes ports; the API and the database are on an internal network without outbound access.
- Containers run as non-root with a read-only filesystem. Keep `.env` private.
- Uploads are limited to 100 MiB and checked before they are opened; spreadsheet files with active content (macros) are reported, never run.
- See [SECURITY_MODEL.md](SECURITY_MODEL.md) for the threat model.

## 8. Known limits
One API process; open workbooks are held in memory, so the server does not scale across machines. Large imports and exports run as background jobs. Exact numbers: [LIMITS.md](LIMITS.md).

## 9. Troubleshooting
| Symptom | Check |
|---|---|
| `docker compose up` stops at once | `POSTGRES_PASSWORD` is missing or empty in `.env` |
| Browser says the connection is not private | self-signed certificate; install a real one (TLS.md) |
| Sign-in loops back to the sign-in page | you opened the site over plain HTTP; use HTTPS |
| Upload fails with 413 | file larger than 100 MiB |
| "Too many requests" at sign-in | the login throttle (10 attempts a minute per address); wait a minute |
| A user forgot the password | `reset-password` (section 3) |
