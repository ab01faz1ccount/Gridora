# apps/web/e2e — real-browser checks (Firefox + Selenium)

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
