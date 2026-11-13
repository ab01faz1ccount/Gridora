# ruff: noqa  (scratch spike script, not product code)
import sys, time, zipfile, resource
sys.path.insert(0, "opx_site")
import openpyxl
print("openpyxl", openpyxl.__version__)
def parts(p):
    with zipfile.ZipFile(p) as z: return {n: z.read(n) for n in z.namelist()}
wb = openpyxl.load_workbook("fx/extras.xlsx", keep_vba=True)
wb.save("fx/extras_opx.xlsx")
a, b = parts("fx/extras.xlsx"), parts("fx/extras_opx.xlsx")
print("input parts", len(a), "output parts", len(b))
print("LOST:", sorted(set(a)-set(b)))
print("byte-identical:", sorted(n for n in a if n in b and a[n]==b[n]))
s1 = b["xl/worksheets/sheet1.xml"].decode(); s2 = b["xl/worksheets/sheet2.xml"].decode()
for k, v in {"mergeCells":"<mergeCell ","conditionalFormatting":"conditionalFormatting","dataValidations":"dataValidation","drawing":"<drawing","extLst keep-me":"keep-me","RTL":None}.items():
    ok = ('rightToLeft="1"' in s2) if v is None else (v in s1)
    print(("KEPT " if ok else "LOST "), k)
print("macroEnabled:", "macroEnabled" in b["[Content_Types].xml"].decode())
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
t=time.perf_counter(); wb=openpyxl.load_workbook("fx/big.xlsx"); print(f"load big.xlsx (normal mode) {time.perf_counter()-t:.1f}s maxRSS {rss():.0f} MB")
