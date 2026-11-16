import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_lib import *
import random

ROWS, COLS = 100_000, 20
p = os.path.join(os.environ.get("TMPDIR", "/tmp"), "data100k.csv")
if not os.path.exists(p):
    random.seed(1)
    names = ["علی", "رضا", "مریم", "سارا", "حسین", "نرگس", "تهران", "شیراز", "اصفهان", "تبریز"]
    with open(p, "w", encoding="utf-8") as f:
        f.write(",".join(["نام"] + [f"ستون{c}" for c in range(1, COLS)]) + "\n")
        for r in range(1, ROWS):
            f.write(",".join([random.choice(names) + str(r)] + [f"{random.randint(0, 100000)}.{random.randint(0,99):02d}" for _ in range(COLS - 1)]) + "\n")
print("csv MB:", os.path.getsize(p) / 1e6, flush=True)

login()
ws = api("POST", "/workspaces", {"name": "bench100k"})["data"]["id"]
t0 = time.time(); job = upload_csv(ws, "bench.csv", p); print("upload s:", round(time.time() - t0, 1), flush=True)
j, secs = wait_job(job); print("import job:", j["status"], round(secs, 1), "s", flush=True)
assert j["status"] == "succeeded", j
wb = j["result_ref"]; meta = api("GET", f"/workbooks/{wb}")["data"]
print("sheet:", meta["sheets"][0]["row_count"], "x", meta["sheets"][0]["col_count"], flush=True)

d = make_driver()
try:
    ui_login(d)
    t0 = time.time(); d.get(f"{BASE}/workbooks/{wb}")
    wait_for(d, lambda: loaded_text(d), 60, "first loaded cell")
    print("time to first data cell after navigation: %.2fs" % (time.time() - t0), flush=True)
    print("rendered cells (initial):", cells_js(d), " /cells requests:", cell_requests(d), flush=True)
    print("first cell text:", loaded_text(d), flush=True)
    sc = d.find_element(By.CSS_SELECTOR, "[role=grid]")
    print("scroll proxy:", d.execute_script("const e=document.querySelector('[role=grid]'); return [e.scrollHeight, e.clientHeight, e.dataset.scaled||'no']"), flush=True)
    d.save_screenshot("shot_100k_ltr.png")

    # jump to the middle and to the bottom
    for label, frac in (("middle", 0.5), ("bottom", 1.0)):
        r0 = cell_requests(d)
        t0 = time.time()
        d.execute_script("const e=document.querySelector('[role=grid]'); e.scrollTop = (e.scrollHeight - e.clientHeight) * arguments[0];", frac)
        wait_for(d, lambda: d.execute_script("return !!document.querySelector('.gv-cell:not(.gv-loading)')") and
                 d.execute_script("const cs=[...document.querySelectorAll('.gv-cell:not(.gv-loading)')]; return cs.length>40"), 30, label)
        dt = time.time() - t0
        rows = d.execute_script("return [...new Set([...document.querySelectorAll('[role=gridcell]')].map(e=>+e.dataset.r))].sort((a,b)=>a-b)")
        print(f"jump {label}: {dt:.2f}s to populated; rows {rows[0]}..{rows[-1]}, cells {cells_js(d)}, new requests {cell_requests(d)-r0}", flush=True)
    d.save_screenshot("shot_100k_bottom.png")

    # sweep scroll: 15 rows per frame for 4 seconds, from the top
    d.execute_script("document.querySelector('[role=grid]').scrollTop = 0")
    time.sleep(1)
    r0 = cell_requests(d)
    res = d.execute_async_script(BENCH_JS, 4000, 390)
    fr = res["frames"][1:]
    print(f"sweep: {len(fr)} frames in 4s, scrolled {res['scrolled']:.0f}px (~{res['scrolled']/26:.0f} rows)", flush=True)
    print(f"  frame ms: p50 {pct(fr,.5):.1f}  p95 {pct(fr,.95):.1f}  max {max(fr):.1f}  >50ms: {sum(1 for x in fr if x>50)}", flush=True)
    print(f"  new /cells requests during sweep: {cell_requests(d)-r0}, rendered cells now: {cells_js(d)}", flush=True)
    time.sleep(1.5)
    print("  after settling: populated cells:", d.execute_script("return document.querySelectorAll('.gv-cell:not(.gv-loading)').length"), "loading:", d.execute_script("return document.querySelectorAll('.gv-loading').length"), flush=True)
finally:
    d.quit()
print("DONE")
