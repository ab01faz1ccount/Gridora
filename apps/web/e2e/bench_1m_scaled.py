import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_lib import *
ROWS = 1_048_000
p = os.path.join(os.environ.get("TMPDIR", "/tmp"), "data1m.csv")
if not os.path.exists(p):
    with open(p, "w") as f:
        f.write("n\n"); f.writelines(f"{r}\n" for r in range(1, ROWS))
login()
ws = api("POST", "/workspaces", {"name": "bench1m"})["data"]["id"]
job = upload_csv(ws, "m.csv", p); j, secs = wait_job(job); print("import:", j["status"], round(secs, 1), "s", flush=True)
assert j["status"] == "succeeded", j
wb = j["result_ref"]; meta = api("GET", f"/workbooks/{wb}")["data"]; print("rows:", meta["sheets"][0]["row_count"], flush=True)
d = make_driver()
try:
    ui_login(d)
    d.get(f"{BASE}/workbooks/{wb}")
    wait_for(d, lambda: loaded_text(d), 60, "cells")
    info = d.execute_script("const e=document.querySelector('[role=grid]'); return {scrollHeight:e.scrollHeight, clientHeight:e.clientHeight, scaled:e.dataset.scaled||null, rows:e.dataset.rows}")
    print("scroller:", info, "(a proxy of 10,000,028 px accepted by Firefox => scrollHeight should equal it)", flush=True)
    last = lambda: d.execute_script("const hs=[...document.querySelectorAll('.gv-rowhdr-cell')]; return hs.length? hs[hs.length-1].textContent : null")
    firstv = lambda: d.execute_script("const hs=[...document.querySelectorAll('.gv-rowhdr-cell')]; return hs.length? hs[0].textContent : null")
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        d.execute_script("const e=document.querySelector('[role=grid]'); e.scrollTop=(e.scrollHeight-e.clientHeight)*arguments[0]", frac)
        wait_for(d, lambda: d.execute_script("return document.querySelectorAll('.gv-cell:not(.gv-loading)').length>20"), 20, f"populated at {frac}")
        time.sleep(0.3)
        vis = d.execute_script("""const g=document.querySelector('[role=grid]').getBoundingClientRect(); const rows=[...document.querySelectorAll('.gv-cell[data-c="0"]')].filter(e=>{const b=e.getBoundingClientRect(); return b.bottom>g.top+28 && b.top<g.bottom}); return rows.map(e=>+e.dataset.r)""")
        txt = d.execute_script("const g=document.querySelector('[role=grid]').getBoundingClientRect(); const rows=[...document.querySelectorAll('.gv-cell[data-c=\"0\"]')].filter(e=>{const b=e.getBoundingClientRect(); return b.bottom>g.top+28 && b.top<g.bottom}); return rows.map(e=>e.textContent)")
        print(f"scroll {int(frac*100):3d}%: visible rows {min(vis)}..{max(vis)} (value in col A: {txt[0]}..{txt[-1]}), rendered cells {cells_js(d)}", flush=True)
    d.save_screenshot("shot_1m_bottom.png")
    # last row really is the last
    print("last visible row index == last row of the sheet:", max(vis) == meta["sheets"][0]["row_count"] - 1, flush=True)
    d.execute_script("document.querySelector('[role=grid]').scrollTop = 0"); time.sleep(0.5)
    res = d.execute_async_script(BENCH_JS, 3000, 4000)
    fr = res["frames"][1:]
    print(f"sweep (scaled, 4000px/frame): p50 {pct(fr,.5):.1f}ms p95 {pct(fr,.95):.1f}ms max {max(fr):.1f}ms frames {len(fr)}", flush=True)
finally:
    d.quit()
print("DONE")
