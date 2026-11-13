# ruff: noqa  (scratch spike script, not product code)
import zipfile, sys
sys.path.insert(0, ".")
import build_fx
build_fx.build("fx/_h.xlsx", extras=False)
src = zipfile.ZipFile("fx/_h.xlsx")
def rewrite(path, edits=None, extra=None, stream=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            if stream and n == stream[0]: continue
            d = (edits or {}).get(n, src.read(n))
            z.writestr(n, d)
        for n, d in (extra or {}).items(): z.writestr(n, d)
        if stream:
            n, size = stream
            with z.open(n, "w", force_zip64=True) as f:
                f.write(b'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
                blk = b" " * (1 << 20)
                for _ in range(size >> 20): f.write(blk)
                f.write(b"</sheetData></worksheet>")
# 1 zip bomb: 1.5 GB of spaces in sheet2
rewrite("fx/h_bomb.xlsx", stream=("xl/worksheets/sheet2.xml", 1500 << 20))
# 2 XXE in sharedStrings
sst = src.read("xl/sharedStrings.xml").decode()
xxe = ('<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY xxe SYSTEM "file:///etc/hostname">]>' + sst.split("?>", 1)[1].replace("<t>name</t>", "<t>&xxe;</t>"))
rewrite("fx/h_xxe.xlsx", edits={"xl/sharedStrings.xml": xxe.encode()})
# 3 billion laughs
bl = '<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;"><!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;"><!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;"><!ENTITY g "&f;&f;&f;&f;&f;&f;&f;&f;&f;&f;">]>' + sst.split("?>", 1)[1].replace("<t>name</t>", "<t>&g;</t>")
rewrite("fx/h_laughs.xlsx", edits={"xl/sharedStrings.xml": bl.encode()})
# 4 path traversal entry + absolute
rewrite("fx/h_trav.xlsx", extra={"../../evil.txt": b"x", "/abs/evil.txt": b"x"})
# 5 absurd dimension / far cell
sh = src.read("xl/worksheets/sheet1.xml").decode().replace('<c r="A1" t="s">', '<c r="XFD1048576" t="s">', 1)
rewrite("fx/h_far.xlsx", edits={"xl/worksheets/sheet1.xml": sh.encode()})
sh2 = src.read("xl/worksheets/sheet1.xml").decode().replace('<c r="A1" t="s">', '<c r="XFE1048577" t="s">', 1)
rewrite("fx/h_beyond.xlsx", edits={"xl/worksheets/sheet1.xml": sh2.encode()})
print("built")
