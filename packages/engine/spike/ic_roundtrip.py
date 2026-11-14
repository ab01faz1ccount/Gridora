# ruff: noqa  (scratch spike script, not product code)
import sys, zipfile, hashlib
sys.path.insert(0, "ic_site")
import ironcalc as ic
def parts(p):
    with zipfile.ZipFile(p) as z:
        return {n: z.read(n) for n in z.namelist()}
for name in ("plain", "extras"):
    src = f"fx/{name}.xlsx"; dst = f"fx/{name}_ic.xlsx"
    try:
        m = ic.load_from_xlsx(src, "en", "UTC", "en")
        m.evaluate()
        print(name, "loaded; sheets:", [s["name"] if isinstance(s, dict) else s for s in m.get_worksheets_properties()])
        m.save_to_xlsx(dst)
    except Exception as e:
        print(name, "FAILED:", type(e).__name__, str(e)[:200]); continue
    a, b = parts(src), parts(dst)
    print("  input parts :", len(a), " output parts:", len(b))
    print("  LOST (in input, absent in output):", sorted(set(a) - set(b)))
    print("  NEW  (only in output):", sorted(set(b) - set(a)))
    same = [n for n in a if n in b and a[n] == b[n]]
    print("  byte-identical parts:", sorted(same))
