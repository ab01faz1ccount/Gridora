# Limits and measured performance

Numbers below were measured by `apps/web/e2e/perf_real.py` on the real stack (real engine, PostgreSQL 16, one uvicorn worker, Chromium),
on a 2-vCPU / 8 GB sandbox, API called directly (no nginx). Data from `apps/web/e2e/perf_gen.py`: 100,000 rows x 10 columns
(CSV 11.8 MB, XLSX 9.8 MB) and a formulas workbook (4.0 MB: `F=SUM(A:E)`, `G=F*2` per row plus one `SUM` over all 100,000 rows).
Treat them as an order of magnitude, not a promise: re-run the script on your hardware.

| Measurement (100,000 rows) | CSV | XLSX | XLSX with 200,000 formulas |
|---|---|---|---|
| Upload + import job | 2.4–3.7 s | 1.0–1.1 s (lazy parse) | 12.7 s (includes one full recalculation) |
| First 100x26 window | < 0.5 s | ~20 ms | ~15 ms |
| Window at the last rows | ~20 ms | ~40 ms | ~17 ms |
| Edit one cell | 12–21 ms | 14–16 ms | 67–139 ms (recalculates dependents, incl. the 100,000-row SUM) |
| Edit 10,000 cells in one request / undo it | 0.5 s / 0.4 s | | undo of one edit: 13 ms |
| Clear 50,000 cells (the per-request maximum) | 2.5 s | | |
| API memory after import (RSS) | ~765 MB | ~885 MB | ~1.2 GB |

Browser (Chromium, formulas workbook): open to first cells 0.4 s; Ctrl+End to row 100,000 0.2 s; type + Enter until the screen shows the
value 0.1 s; 60 x PageDown 2.6 s; about 480 cells in the DOM at any time (virtual scrolling).

## Hard limits (enforced)
- Upload: 100 MiB per file (nginx streams it; the API checks again).
- One edit/paste/clear request: at most 50,000 cells = one undo step. Larger selections are refused with a message.
- Paste beyond Excel's grid (1,048,576 rows, 16,384 columns) is dropped.
- A single API worker: requests of one process are served one by one, and imports/recalculation hold the engine.

## Known limits (not enforced, be aware)
- Memory is the real ceiling: roughly 8–12 KB of RAM per formula cell, 7–9 KB per data cell in the open workbook. 100,000 x 10 plus formulas needs about 1.2 GB of API memory; several large workbooks open at once add up.
- The first full recalculation of a large imported file happens inside the import job (13 s for 200,000 formulas).
- Paste does not shift relative references in formulas; dates pasted from text stay text; no optimistic display (the screen shows what the server computed, after the round trip).
- Docker images were not built in the sandbox (see `deploy/README.md`), so numbers behind nginx and in containers are unmeasured.
- Formula coverage gaps are listed in `docs/INTEGRATION_PLAN.md` (step 8).
