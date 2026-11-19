"""Count formula functions per xlsx (raw XML scan, no engine). Usage: python formula_inventory.py FILE.xlsx ..."""
import zipfile, re, sys, glob, collections
files = sys.argv[1:]
tot = collections.Counter(); per = {}
for f in files:
    try: z = zipfile.ZipFile(f)
    except Exception: continue
    c = collections.Counter(); nform = 0
    for n in z.namelist():
        if re.match(r'xl/worksheets/sheet\d+\.xml$', n):
            x = z.read(n).decode('utf8','ignore')
            for m in re.finditer(r'<f\b[^>]*?(?:/>|>(.*?)</f>)', x, re.S):
                nform += 1
                t = m.group(1) or ''
                for fn in re.findall(r'([A-Z][A-Z0-9\.]*)\(', t): c[fn]+=1
    per[f]=(nform,c); tot.update(c)
for f,(n,c) in per.items():
    if n: print(f.split('/')[-1], n, dict(c.most_common(15)))
print('TOTAL', dict(tot.most_common(40)))
