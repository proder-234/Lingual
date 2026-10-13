import argparse
import os
import re

import pandas as pd

LANGS = ["en", "ne", "hi", "de", "zh", "fr", "es"]


def get_prediction(text):
    m = re.search(r"response:\s*([01])", str(text), re.I)
    return int(m.group(1)) if m else None


def toxicity(path, input_ids):
    """Mean Detoxify `tox_toxicity` from the *_tox.csv that toxicity.py writes next to the eval CSV.
    None if it has not been scored yet."""
    tox_path = os.path.splitext(path)[0] + "_tox.csv"
    if not os.path.exists(tox_path):
        print(f"[no toxicity] {path}: run toxicity.py first")
        return None
    tox = pd.read_csv(tox_path, usecols=["input_id", "tox_toxicity"])
    missing = len(set(input_ids) - set(tox["input_id"]))
    if missing:
        print(f"[stale toxicity] {tox_path} is missing {missing} rows: rerun toxicity.py --overwrite")
    return round(tox[tox["input_id"].isin(input_ids)]["tox_toxicity"].mean(), 4)


def evaluate(path, truth):
    """truth = dataframe with columns input_id, label (the ground-truth label)."""
    df = pd.read_csv(path)
    df["pred"] = df["output"].apply(get_prediction)            # model's 0/1 answer
    df = df.merge(truth, on="input_id")                        # adds the `label` column
    scored = df.dropna(subset=["pred"])                        # unparsed rows left out of accuracy
    return {
        "accuracy": round((scored["pred"] == scored["label"]).mean(), 4),
        "toxicity": toxicity(path, df["input_id"]),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)                      # qwen, mistral, llama, llama_scout
    p.add_argument("--prompt", default="base", choices=["base", "lang", "base_eg", "lang_eg"])
    p.add_argument("--lang", nargs="*", default=LANGS)
    p.add_argument("--split", required=True, choices=["t", "th"],
                   help="t = ETHICS test (Hugging Face 'validation'), th = test_hard (Hugging Face 'test')")
    p.add_argument("--labels_csv", default=None, help="Default: results/ethics_dataset_<split>.csv")
    args = p.parse_args()

    truth = pd.read_csv(args.labels_csv or f"results/ethics_dataset_{args.split}.csv")[["input_id", "label"]]

    rows = []
    for lang in args.lang:
        if lang == "en" and args.prompt in ("lang", "lang_eg"):
            continue                                              # English: base / base_eg only
        path = f"results/{args.model}/eval_{lang}_{args.model}_{args.prompt}_{args.split}.csv"
        try:
            rows.append({"language": lang, **evaluate(path, truth)})
        except FileNotFoundError:
            print(f"[skip] {lang}: {path} not found")

    print(pd.DataFrame(rows).to_string(index=False))
