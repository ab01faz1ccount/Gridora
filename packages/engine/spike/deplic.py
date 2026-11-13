# ruff: noqa  (scratch spike script, not product code)
import re, json, time, urllib.request, sys
lock = open("ironcalc/Cargo.lock").read()
pk = re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"(?:\nsource = "([^"]+)")?', lock)
reg = [(n, v) for n, v, s in pk if s and s.startswith("registry")]
print("packages:", len(pk), "from registry:", len(reg), file=sys.stderr)
out = {}
for n, v in reg:
    url = f"https://crates.io/api/v1/crates/{n}/{v}"
    req = urllib.request.Request(url, headers={"User-Agent": "gridora-spike (license audit)"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=20))
        out[f"{n} {v}"] = d["version"].get("license")
    except Exception as e:
        out[f"{n} {v}"] = f"ERR {type(e).__name__}"
    time.sleep(0.25)
json.dump(out, open("deplic.json", "w"), indent=1)
from collections import Counter
print(Counter(out.values()).most_common())
