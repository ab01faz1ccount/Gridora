# ruff: noqa  (scratch spike script, not product code)
import sys, time, resource
sys.path.insert(0, "ic_site")
import ironcalc as ic
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
m = ic.create("feed", "en", "UTC", "en")
N_ROWS = 100_000
t = time.perf_counter()
for r in range(1, N_ROWS + 1):
    for c in range(1, 19):
        if c % 5 in (3, 4, 0): m.update_cell_with_text(0, r, c, "text value")
        else: m.update_cell_with_number(0, r, c, r * 0.5 + c)
    m.update_cell_with_formula(0, r, 19, f"=A{r}*2+B{r}")
print(f"fed {N_ROWS*19} cells (raw typed API) in {time.perf_counter()-t:.2f} s, maxRSS {rss():.0f} MB")
t = time.perf_counter(); m.evaluate(); print(f"evaluate {time.perf_counter()-t:.2f} s")
t = time.perf_counter(); m.update_cell_with_number(0, 5, 1, 42.0); m.evaluate(); print(f"edit one cell + evaluate {time.perf_counter()-t:.2f} s")
print("T5 =", m.get_cell_value(0, 5, 19))
