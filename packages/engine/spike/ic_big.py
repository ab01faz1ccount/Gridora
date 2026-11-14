# ruff: noqa  (scratch spike script, not product code)
import sys, time, resource
sys.path.insert(0, "ic_site")
import ironcalc as ic
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
t=time.perf_counter(); m=ic.load_from_xlsx("fx/big.xlsx","en","UTC","en"); print(f"load_from_xlsx        {time.perf_counter()-t:7.2f} s   maxRSS {rss():.0f} MB")
t=time.perf_counter(); m.evaluate(); print(f"evaluate (100k formulas){time.perf_counter()-t:6.2f} s   maxRSS {rss():.0f} MB")
t=time.perf_counter()
for r in range(1,101):
    for c in range(1,21): m.get_cell_value(0, r, c)
print(f"read 100x20 window via per-cell calls  {time.perf_counter()-t:7.3f} s")
t=time.perf_counter()
for r in range(1,1001):
    for c in range(1,21): m.get_cell_value(0, r, c)
print(f"read 1000x20 window via per-cell calls {time.perf_counter()-t:7.3f} s")
t=time.perf_counter(); m.set_user_input(0, 5, 1, "42"); m.evaluate(); print(f"edit A5 + full evaluate {time.perf_counter()-t:6.2f} s")
t=time.perf_counter(); m.save_to_xlsx("fx/big_ic.xlsx"); print(f"save_to_xlsx          {time.perf_counter()-t:7.2f} s   maxRSS {rss():.0f} MB")
print("C5 =", m.get_cell_value(0,5,20), "formula:", m.get_cell_formula(0,5,20))
