# ruff: noqa  (scratch spike script, not product code)
import sys, time, resource, atexit
sys.path.insert(0, "ic_site")
import ironcalc as ic
name = sys.argv[1]
resource.setrlimit(resource.RLIMIT_AS, (3 << 30, 3 << 30))
t = time.perf_counter()
try:
    m = ic.load_from_xlsx(f"fx/{name}.xlsx", "en", "UTC", "en")
    v = m.get_cell_value(0, 1, 1) if name in ("h_xxe", "h_laughs") else "-"
    print(f"{name}: LOADED in {time.perf_counter()-t:.1f}s; A1={str(v)[:60]!r} len={len(str(v))}")
except BaseException as e:
    print(f"{name}: raised {type(e).__name__}: {str(e)[:100]!r} after {time.perf_counter()-t:.1f}s")
atexit.register(lambda: print(f"  maxRSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB"))
