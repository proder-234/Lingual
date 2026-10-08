"""
Score model justifications with Detoxify's multilingual model.

Reads every eval CSV matching --pattern, runs the `justification` column through
Detoxify('multilingual'), and writes a copy with tox_* score columns added
(e.g. eval_de_qwen_base.csv -> eval_de_qwen_base_tox.csv). Originals are not modified.

Install:  pip install detoxify
Run:      python score_toxicity.py
          python score_toxicity.py --pattern "results/mistral/eval_*.csv"
"""
import argparse
import glob
import os
import re

import pandas as pd
import torch
from detoxify import Detoxify
from tqdm import tqdm


# Labels that start the justification inside the `output` column.
# If some prompts make models write a translated label (e.g. "Begründung:"), add it here.
JUSTIFICATION_LABELS = ["justification"]
_JUST_RE = re.compile(
    r"(?:^|\n)\s*\**\s*(?:" + "|".join(map(re.escape, JUSTIFICATION_LABELS)) + r")\s*\**\s*[:：]\s*\**\s*(.*)",
    flags=re.IGNORECASE | re.DOTALL,
)


def extract_justification(output):
    """Pull everything after 'justification:' out of the raw output block. '' if not found."""
    m = _JUST_RE.search(str(output)) if pd.notna(output) else None
    return m.group(1).strip() if m else ""


def score_texts(model, texts, batch_size):
    """Return a DataFrame of Detoxify scores aligned to `texts` (NaN for empty rows)."""
    texts = pd.Series(texts).fillna("").astype(str).str.strip()
    nonempty = texts[texts != ""]

    rows = []
    for s in tqdm(range(0, len(nonempty), batch_size), desc="  batches", leave=False):
        batch = nonempty.iloc[s:s + batch_size].tolist()
        rows.append(pd.DataFrame(model.predict(batch)))

    scores = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    scores.index = nonempty.index
    scores = scores.reindex(texts.index)        # empty justifications -> NaN scores
    return scores.add_prefix("tox_")


def main():
    parser = argparse.ArgumentParser(description="Add Detoxify multilingual toxicity scores to eval CSVs.")
    parser.add_argument("--pattern", default="results/**/eval_*.csv",
                        help="Glob for input CSVs (recursive).")
    parser.add_argument("--col", default="justification", help="Column to score.")
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-score files that already have a *_tox.csv output.")
    args = parser.parse_args()

    files = [f for f in sorted(glob.glob(args.pattern, recursive=True)) if not f.endswith("_tox.csv")]
    if not files:
        print(f"No files match {args.pattern}")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Detoxify multilingual on {device}...")
    model = Detoxify("multilingual", device=device)

    for path in files:
        out_path = os.path.splitext(path)[0] + "_tox.csv"
        if os.path.exists(out_path) and not args.overwrite:
            print(f"Skip (already scored): {path}")
            continue

        df = pd.read_csv(path)
        if args.col not in df.columns:
            if "output" not in df.columns:
                print(f"Skip (no '{args.col}' or 'output' column): {path}  columns={list(df.columns)}")
                continue
            df[args.col] = df["output"].apply(extract_justification)
            missing = int((df[args.col] == "").sum())
            if missing:
                print(f"  warning: no 'justification:' found in {missing}/{len(df)} rows (scored as NaN)")

        print(f"Scoring {path} ({len(df)} rows)")
        scores = score_texts(model, df[args.col], args.batch_size)
        df = pd.concat([df.drop(columns=[c for c in scores.columns if c in df.columns]), scores], axis=1)
        df.to_csv(out_path, index=False)
        print(f"  mean toxicity: {df['tox_toxicity'].mean():.4f}  -> {out_path}")

    print("Done!")


if __name__ == "__main__":
    main()
