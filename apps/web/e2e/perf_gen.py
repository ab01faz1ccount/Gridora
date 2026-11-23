"""Makes the 100,000-row test files (needs openpyxl): python perf_gen.py OUT_DIR
  plain100k.csv        100,000 x 20: ids, Persian and Latin text, numbers, dates as text
  plain100k.xlsx       same data, no formulas
  formulas100k.xlsx    100,000 rows: A..E numbers, F = SUM(A:E) per row, G = F*2, and a total H1 = SUM(F2:F100001)
"""
import csv
import os
import random
import sys

import openpyxl

out = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(out, exist_ok=True)
random.seed(7)
ROWS = 100_000
names = ["علی", "مریم", "Reza", "Sara", "حسین", "Nima", "زهرا", "Omid"]
header = [f"col{i}" for i in range(20)]


def row(i):
    return [i, names[i % 8], random.randint(0, 10_000), round(random.random() * 1000, 2), f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}"] + [
        random.randint(0, 1000) if j % 2 else names[(i + j) % 8] for j in range(15)
    ]


rows = [row(i) for i in range(ROWS)]
with open(os.path.join(out, "plain100k.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)

wb = openpyxl.Workbook(write_only=True)
ws = wb.create_sheet("Data")
ws.append(header)
for r in rows:
    ws.append(r)
wb.save(os.path.join(out, "plain100k.xlsx"))

wb = openpyxl.Workbook(write_only=True)
ws = wb.create_sheet("Calc")
ws.append(["a", "b", "c", "d", "e", "sum", "double", "", "total"])
for i in range(2, ROWS + 2):
    ws.append([random.randint(0, 100) for _ in range(5)] + [f"=SUM(A{i}:E{i})", f"=F{i}*2"] + ([None, f"=SUM(F2:F{ROWS + 1})"] if i == 2 else []))
wb.save(os.path.join(out, "formulas100k.xlsx"))
print("generated")
