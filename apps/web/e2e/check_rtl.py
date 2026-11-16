import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_lib import *
login()
ws = api("POST", "/workspaces", {"name": "rtl"})["data"]["id"]
open("rtl.csv", "w", encoding="utf-8").write("نام,تعداد,شهر,مبلغ\n" + "".join(f"علی{r},{r*3},تهران,{r*1000.5}\n" for r in range(1, 400)))
job = upload_csv(ws, "rtl.csv", "rtl.csv"); j, _ = wait_job(job); wb = j["result_ref"]
d = make_driver()
try:
    ui_login(d)
    d.get(f"{BASE}/workbooks/{wb}")
    wait_for(d, lambda: loaded_text(d), 30, "cells")
    sc = d.find_element(By.CSS_SELECTOR, "[role=grid]")
    print("grid dir attr:", sc.get_attribute("dir"))
    geo = d.execute_script("""
      const g=document.querySelector('[role=grid]').getBoundingClientRect();
      const cell=(r,c)=>document.querySelector(`[data-r="${r}"][data-c="${c}"]`).getBoundingClientRect();
      const a=cell(0,0), b=cell(0,1), rh=document.querySelector('.gv-rowhdr-cell').getBoundingClientRect();
      return {gridLeft:g.left, gridRight:g.right, A:[a.left,a.right], B:[b.left,b.right], rowHdr:[rh.left, rh.right]};""")
    print("geometry:", geo)
    print("A is right of B:", geo["A"][0] > geo["B"][0], "| row header on the right edge:", abs(geo["rowHdr"][1]-geo["gridRight"])<20, "| A just left of the row header:", abs(geo["A"][1]-geo["rowHdr"][0])<2)
    d.save_screenshot("shot_rtl.png")
    # keyboard: ArrowLeft should move to the NEXT column (visual left)
    sc.click()
    sc.send_keys(Keys.CONTROL, Keys.HOME)
    active = lambda: d.execute_script("const a=document.querySelector('.gv-active'); return a? [+a.dataset.r,+a.dataset.c]:null")
    print("active at start:", active())
    sc.send_keys(Keys.ARROW_LEFT); print("after ArrowLeft :", active(), "(expect [0,1])")
    sc.send_keys(Keys.ARROW_LEFT); print("after ArrowLeft :", active(), "(expect [0,2])")
    sc.send_keys(Keys.ARROW_RIGHT); print("after ArrowRight:", active(), "(expect [0,1])")
    sc.send_keys(Keys.ARROW_DOWN); print("after ArrowDown :", active(), "(expect [1,1])")
    sc.send_keys(Keys.TAB); print("after Tab       :", active(), "(expect [1,2])")
    sc.send_keys(Keys.END); print("after End       :", active(), "(expect [1,3])")
    sc.send_keys(Keys.HOME); print("after Home      :", active(), "(expect [1,0])")
    # visual check of the active cell position vs its neighbour after moving
    sl = d.execute_script("return document.querySelector('[role=grid]').scrollLeft")
    print("scrollLeft (RTL, <=0):", sl)
    d.save_screenshot("shot_rtl_after.png")
finally:
    d.quit()
print("DONE")
