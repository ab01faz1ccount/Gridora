# apps/web/e2e — real-browser checks

## `real_stack.py` (Chromium + Playwright): the editing slice on the real engine
Sign in -> workspace -> upload `fixtures/people.csv` and `fixtures/sales.xlsx` -> grid -> edit, formulas (real engine), undo/redo,
real Ctrl+C / Ctrl+V, history panel, a conflict made by a second tab, cross-sheet recalculation (`others`). 28 checks, one line each.
```bash
# API: GRIDORA_ENV=dev GRIDORA_SECURE_COOKIES=false GRIDORA_ENGINE=real GRIDORA_DATAOPS=real (+ Postgres, alembic upgrade head,
#      GRIDORA_BOOTSTRAP_ADMIN_USERNAME/PASSWORD), uvicorn on :8000;  web: `npx vite` on :5173 (proxies /api)
BASE_URL=http://127.0.0.1:5173 E2E_USER=admin E2E_PASSWORD=... python e2e/real_stack.py   # exit 1 if any check fails
```
Screenshots go to `E2E_SHOTS` (default /tmp/e2e-shots). It creates a workspace per run and does not clean up. Not in CI yet.

---
## Older scripts (Firefox + Selenium)

These scripts drive **headless Firefox through the real stack** (nginx + API + PostgreSQL; see `deploy/`)
and print measurements. They are scripts, not a CI suite yet, and they are **not Playwright** (the
Playwright browsers cannot be downloaded in the sandbox where this was written; Firefox 160 and geckodriver
came from conda-forge). Nothing here is asserted by CI today.

```bash
pip install selenium
export BASE_URL=https://localhost E2E_USER=admin E2E_PASSWORD='...'
export FIREFOX_BIN=/path/to/firefox GECKODRIVER=/path/to/geckodriver   # defaults: /opt/ffenv/bin/*
python e2e/bench_100k.py        # 100,000 x 20 sheet: render bound, requests, jumps, scroll frame times
python e2e/bench_1m_scaled.py   # 1,048,000 rows: scaled scrolling, last row reachable
python e2e/check_rtl.py         # RTL layout + keyboard (needs e2e/nginx-rtl-test.conf, see the file)
```
The scripts create (and do not clean up) workspaces named `bench100k`, `bench1m`, `rtl`.
Numbers depend on the machine (the reference run was 1 CPU, 4 GB, no GPU, software rendering).
