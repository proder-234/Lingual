"""Re-translate the cells of results/ethics_translated.csv where NLLB dropped a sentence.

The original translate.py merged sentences into one chunk before sending them to NLLB, which
sometimes translated only the first sentence. A cell is treated as broken when its English
text has 2+ sentences and either
  * the translation has fewer sentences AND is much shorter than usual for that language
    (< 0.75 x the language's median length ratio) -- a merged-but-complete translation
    ("..., y ...") keeps its normal length and is left alone, or
  * Scenario1 and Scenario2 became identical in that language.
Only those cells are re-translated (one sentence at a time, with the fixed split_text());
every other translation is kept exactly as it was.

    NLLB_FP16=1 python3 retranslate_multisentence.py

Writes results/ethics_translated.csv in place and results/retranslated_cells.csv with the
old and new text of every re-translated cell.
"""
import csv
import os
import re
import statistics

import pandas as pd

import translate as T  # loads NLLB (translate.MODEL) and the fixed split_text()

CSV = "results/ethics_translated.csv"
FIELDS = ["Scenario1", "Scenario2"]
END = re.compile(r"[.!?。！？।]+")


def n_sentences(text):
    return len([s for s in END.split(str(text).strip()) if s.strip()])


def broken_cells(df, lang):
    cells = set()
    for field in FIELDS:
        en, tr = df[f"en_{field}"], df[f"{lang}_{field}"]
        ratio = [len(t) / max(1, len(e)) for e, t in zip(en, tr)]
        med = statistics.median(ratio)
        for i, (e, t, q) in enumerate(zip(en, tr, ratio)):
            if n_sentences(e) >= 2 and n_sentences(t) < n_sentences(e) and q < 0.75 * med:
                cells.add((i, field))
    same = df[f"{lang}_Scenario1"].str.strip() == df[f"{lang}_Scenario2"].str.strip()
    for i in same[same].index:
        for field in FIELDS:
            if n_sentences(df.at[i, f"en_{field}"]) >= 2:
                cells.add((i, field))
    return cells


df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
changes = []

for lang, spec in T.LANGUAGES.items():
    for field in FIELDS:
        idx = sorted(i for i, f in broken_cells(df, lang) if f == field)
        if not idx:
            continue
        new = T.translate_one_lang([df.at[i, f"en_{field}"] for i in idx], "eng_Latn", spec["nllb"],
                                   batch_size=32, desc=f"{lang}:{field} ({len(idx)} cells)")
        for i, text in zip(idx, new):
            changes.append({"input_id": df.at[i, "input_id"], "lang": lang, "field": field,
                            "en": df.at[i, f"en_{field}"], "old": df.at[i, f"{lang}_{field}"], "new": text})
            df.at[i, f"{lang}_{field}"] = text
        tmp = CSV + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, CSV)  # checkpoint after every language/field
        print(f"{lang} {field}: re-translated {len(idx)} cells", flush=True)

with open("results/retranslated_cells.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["input_id", "lang", "field", "en", "old", "new"])
    w.writeheader()
    w.writerows(changes)
print(f"Done: {len(changes)} cells in {len({c['input_id'] for c in changes})} rows")
