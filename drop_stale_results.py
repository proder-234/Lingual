"""Remove model outputs whose input translation changed (listed in results/retranslated_cells.csv),
so the next inference run (which resumes by input_id) re-runs exactly those rows.

    python3 drop_stale_results.py            # all models under results/
"""
import csv
import glob
import os
import re

changed = {}  # lang -> set of input_ids
with open("results/retranslated_cells.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        changed.setdefault(r["lang"], set()).add(r["input_id"])

name_re = re.compile(r"eval_([a-z]+)_.+\.csv$")
for path in sorted(glob.glob("results/*/eval_*.csv")):
    m = name_re.search(os.path.basename(path))
    if not m or m.group(1) not in changed:
        continue
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    keep = [r for r in rows if r["input_id"] not in changed[m.group(1)]]
    if len(keep) == len(rows):
        continue
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["input_id", "output"])
        w.writeheader()
        w.writerows(keep)
    os.replace(tmp, path)
    print(f"{path}: removed {len(rows) - len(keep)} rows with re-translated input")
