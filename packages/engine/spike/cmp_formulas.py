# ruff: noqa  (scratch spike script, not product code)
import sys, csv
sys.path.insert(0, "ic_site"); sys.path.insert(0, ".")
import ironcalc as ic
from formulas_fx import F
m = ic.load_from_xlsx("fx/formulas.xlsx", "en", "UTC", "en"); m.evaluate()
lo = list(csv.reader(open("fx/lo_f/formulas-Sheet1.csv", encoding="utf-8")))
def same(a, b):
    if isinstance(a, bool): a = "TRUE" if a else "FALSE"
    try: return abs(float(a) - float(b)) <= 1e-9 * max(1, abs(float(b)))
    except (TypeError, ValueError): return str(a) == str(b)
ok = diff = 0; rows = []
for i, f in enumerate(F, start=1):
    lov = lo[i-1][5] if len(lo[i-1]) > 5 else ""
    try: icv = m.get_cell_value(0, i, 6)
    except Exception as e: icv = f"EXC {type(e).__name__}"
    if same(icv, lov): ok += 1
    else: diff += 1; rows.append((f, lov, icv))
print(f"{len(F)} formulas: IronCalc == LibreOffice on {ok}; differ on {diff}")
for f, a, b in rows: print(f"  {f:46} LO={a!r:28} IC={b!r}")
