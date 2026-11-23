"""100,000-row performance check on the REAL stack (real engine, Postgres, Chromium).

Makes its own numbers; asserts only loose budgets (a failed budget exits 1, the numbers are printed either way).
    python perf_gen.py DATA_DIR            # once (needs openpyxl)
    PERF_DATA=DATA_DIR python e2e/perf_real.py
Env: API_URL (default http://127.0.0.1:8000), BASE_URL (web, default http://127.0.0.1:5173), E2E_USER/E2E_PASSWORD,
     PERF_DATA, API_PID (to read the API's memory; default: first process matching "uvicorn --factory").
Results are one JSON line at the end: docs/LIMITS.md quotes them with the machine they were made on.
"""
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

API = os.environ.get("API_URL", "http://127.0.0.1:8000") + "/api/v1"
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5173")
USER = os.environ.get("E2E_USER", "admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin-password-123")
DATA = os.environ.get("PERF_DATA", "/home/claude/perf-data")

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
csrf = None
out: dict[str, object] = {}
budget_fail: list[str] = []


def call(method, path, body=None, raw=None, ctype="application/json"):
    headers = {"Content-Type": ctype} if (body is not None or raw) else {}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    data = raw if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    t0 = time.perf_counter()
    try:
        r = opener.open(req)
        status, payload = r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        status, payload = e.code, json.loads(e.read() or b"null")
    return status, payload, (time.perf_counter() - t0) * 1000


def rss_mb() -> float | None:
    pid = os.environ.get("API_PID") or subprocess.run(["pgrep", "-f", "uvicorn --factory"], capture_output=True, text=True).stdout.split()[0:1]
    pid = pid if isinstance(pid, str) else (pid[0] if pid else None)
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


def budget(name: str, value_ms: float, limit_ms: float) -> None:
    out[name] = round(value_ms)
    ok = value_ms <= limit_ms
    print(f"{'PASS' if ok else 'FAIL'} {name}: {value_ms:,.0f} ms (budget {limit_ms:,.0f} ms)", flush=True)
    if not ok:
        budget_fail.append(name)


def upload(ws, path):
    boundary = "----p" + uuid.uuid4().hex
    name = os.path.basename(path)
    raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
           "Content-Type: application/octet-stream\r\n\r\n").encode() + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    t0 = time.perf_counter()
    s, j, ms_up = call("POST", f"/workspaces/{ws}/files", raw=raw, ctype=f"multipart/form-data; boundary={boundary}")
    assert s == 201, (s, j)
    job = j["data"]["job_id"]
    while True:
        s, j, _ = call("GET", f"/jobs/{job}")
        if j["data"]["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    total = (time.perf_counter() - t0) * 1000
    assert j["data"]["status"] == "succeeded", j
    return j["data"]["result_ref"], ms_up, total


def window(wb, sid, r0, rows=100, cols=26):
    s, j, ms = call("GET", f"/workbooks/{wb}/sheets/{sid}/cells?r0={r0}&c0=0&rows={rows}&cols={cols}")
    assert s == 200, (s, j)
    return j["data"]["cells"], ms


def edit(wb, sid, base, edits):
    s, j, ms = call("PATCH", f"/workbooks/{wb}/sheets/{sid}/cells", {"base_seq": base, "edits": edits})
    assert s == 200, (s, str(j)[:300])
    return j["data"], ms


def run_file(ws, fname, key, import_budget_ms):
    path = os.path.join(DATA, fname)
    print(f"--- {fname} ({os.path.getsize(path) / 1e6:.1f} MB)", flush=True)
    wb, ms_up, ms_total = upload(ws, path)
    budget(f"{key}.upload_and_import_ms", ms_total, import_budget_ms)
    sid = call("GET", f"/workbooks/{wb}")[1]["data"]["sheets"][0]["id"]
    out[f"{key}.rss_after_import_mb"] = rss_mb()
    _, ms = window(wb, sid, 0)
    budget(f"{key}.first_window_ms", ms, 3000)
    _, ms = window(wb, sid, 99_900)
    budget(f"{key}.last_rows_window_ms", ms, 3000)
    return wb, sid


def main():
    global csrf
    s, j, _ = call("POST", "/auth/login", {"username": USER, "password": PASSWORD})
    assert s == 200, j
    csrf = j["data"]["csrf_token"]
    s, j, _ = call("POST", "/workspaces", {"name": f"perf-{int(time.time())}"})
    ws = j["data"]["id"]

    # ---- plain data, CSV and XLSX
    wb, sid = run_file(ws, "plain100k.csv", "csv", 120_000)
    seq = 0
    d, ms = edit(wb, sid, seq, [{"r": 50_000, "c": 2, "value": {"k": "num", "n": 1}}])
    seq = d["history_entry"]["seq"]
    budget("csv.edit_one_cell_ms", ms, 1500)
    d, ms = edit(wb, sid, seq, [{"r": r, "c": 2, "value": {"k": "num", "n": r}} for r in range(10_000)])
    seq = d["history_entry"]["seq"]
    budget("csv.edit_10k_cells_ms", ms, 8000)
    s, j, ms = call("POST", f"/documents/{wb}/undo?base_seq={seq}")
    assert s == 200, j
    budget("csv.undo_10k_cells_ms", ms, 8000)
    d, ms = edit(wb, sid, seq - 1, [{"r": r, "c": c} for r in range(5_000) for c in range(10)])
    budget("csv.clear_50k_cells_ms", ms, 15_000)

    wb, sid = run_file(ws, "plain100k.xlsx", "xlsx", 180_000)
    d, ms = edit(wb, sid, 0, [{"r": 99_999, "c": 3, "value": {"k": "num", "n": 7}}])
    budget("xlsx.edit_last_row_ms", ms, 3000)

    # ---- formulas: one edit recalculates a row and a 100,000-cell SUM
    wb, sid = run_file(ws, "formulas100k.xlsx", "formulas", 240_000)
    cells, _ = window(wb, sid, 0, rows=3, cols=9)
    total = [c for c in cells if c["r"] == 1 and c["c"] == 8]
    out["formulas.total_after_import"] = total[0]["v"] if total else None
    print("total (I2) after import:", out["formulas.total_after_import"], flush=True)
    d, ms = edit(wb, sid, 0, [{"r": 1, "c": 0, "value": {"k": "num", "n": 1000}}])
    budget("formulas.edit_input_recalc_ms", ms, 5000)
    after = [c for c in window(wb, sid, 0, rows=3, cols=9)[0] if c["r"] == 1 and c["c"] == 8]
    changed = total and after and total[0]["v"] != after[0]["v"]
    print(f"{'PASS' if changed else 'FAIL'} formulas: the 100,000-row SUM followed the edit ({total[0]['v'] if total else None} -> {after[0]['v'] if after else None})")
    if not changed:
        budget_fail.append("formulas.sum_follows")
    seq = d["history_entry"]["seq"]
    s, j, ms = call("POST", f"/documents/{wb}/undo?base_seq={seq}")
    budget("formulas.undo_recalc_ms", ms, 5000)
    out["api_rss_peak_mb"] = rss_mb()

    # ---- the browser on the formula workbook and the 100k CSV
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, permissions=["clipboard-read", "clipboard-write"])
        ctx.add_init_script("localStorage.setItem('gridora.prefs', JSON.stringify({locale:'en',digits:'latin',calendar:'gregorian'}))")
        page = ctx.new_page()
        page.goto(BASE + "/")
        page.get_by_label("Username").fill(USER)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.get_by_label("Workspace name").wait_for()
        page.goto(f"{BASE}/workbooks/{wb}")
        t0 = time.perf_counter()
        page.wait_for_selector("[role=gridcell]", timeout=30000)
        page.wait_for_function("() => !document.querySelector('[role=gridcell][aria-busy]')", timeout=30000)
        budget("browser.open_formula_workbook_ms", (time.perf_counter() - t0) * 1000, 5000)
        page.get_by_role("grid").focus()
        t0 = time.perf_counter()
        page.keyboard.press("Control+End")
        page.wait_for_selector("#gv-99999-6", timeout=30000)
        page.wait_for_function("() => { const e = document.querySelector('#gv-99999-6'); return e && e.textContent.trim() !== '' }", timeout=30000)
        budget("browser.ctrl_end_to_last_row_ms", (time.perf_counter() - t0) * 1000, 5000)
        page.keyboard.press("Control+Home")
        page.keyboard.type("5")
        t0 = time.perf_counter()
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelector('#gv-0-0')?.textContent.trim() === '5'", timeout=30000)
        # F1 = SUM(A1:E1) is the header row; the data row is row 1: check that its sum follows too
        budget("browser.edit_to_screen_ms", (time.perf_counter() - t0) * 1000, 6000)
        t0 = time.perf_counter()
        for _ in range(60):
            page.keyboard.press("PageDown")
        page.wait_for_function("() => !document.querySelector('[role=gridcell][aria-busy]')", timeout=30000)
        budget("browser.60_pagedowns_ms", (time.perf_counter() - t0) * 1000, 15_000)
        out["browser.dom_cells_rendered"] = page.evaluate("document.querySelectorAll('[role=gridcell]').length")
        b.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 1 if budget_fail else 0


sys.exit(main())
