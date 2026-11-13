# ruff: noqa  (scratch spike script, not product code)
import random, zipfile, sys
sys.path.insert(0, ".")
from build_fx import NS, HDR, R
ROWS, COLS, NSTR = 100_000, 20, 50_000
L = "ABCDEFGHIJKLMNOPQRST"
rnd = random.Random(7)
sst = [f"متن {i} " + "x" * (i % 7) for i in range(NSTR)]
sst_xml = HDR + f'<sst {NS} count="{NSTR}" uniqueCount="{NSTR}">' + "".join(f"<si><t>{s}</t></si>" for s in sst) + "</sst>"
def sheet():
    yield HDR + f'<worksheet {NS}><dimension ref="A1:T{ROWS}"/><sheetData>'
    for r in range(1, ROWS + 1):
        p = [f'<row r="{r}">']
        for c in range(COLS):
            ref = f"{L[c]}{r}"
            if c == 19: p.append(f'<c r="{ref}"><f>A{r}*2+B{r}</f><v>0</v></c>')
            elif rnd.random() < 0.03: continue
            elif c % 5 in (2, 3, 4): p.append(f'<c r="{ref}" t="s"><v>{rnd.randint(0, NSTR-1)}</v></c>')
            else: p.append(f'<c r="{ref}"><v>{rnd.random()*1000:.6f}</v></c>')
        p.append("</row>"); yield "".join(p)
    yield "</sheetData></worksheet>"
import build_fx
build_fx.build("fx/_tmp.xlsx", extras=False)
src = zipfile.ZipFile("fx/_tmp.xlsx")
with zipfile.ZipFile("fx/big.xlsx", "w", zipfile.ZIP_DEFLATED) as z:
    for n in src.namelist():
        if n == "xl/worksheets/sheet1.xml":
            with z.open(n, "w") as f:
                for chunk in sheet(): f.write(chunk.encode())
        elif n == "xl/sharedStrings.xml": z.writestr(n, sst_xml)
        else: z.writestr(n, src.read(n))
import os; print("big.xlsx MB:", os.path.getsize("fx/big.xlsx")/1e6)
