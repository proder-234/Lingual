import argparse
import re

import pandas as pd

LANGS = ["en", "ne", "hi", "de", "zh", "fr", "es"]


def get_prediction(text):
    m = re.search(r"response:\s*([01])", str(text), re.I)
    return int(m.group(1)) if m else None


def accuracy(path, truth):
    """truth = dataframe with columns input_id, label (the ground-truth label)."""
    df = pd.read_csv(path)
    df["pred"] = df["output"].apply(get_prediction)            # model's 0/1 answer
    df = df.merge(truth, on="input_id")                        # adds the `label` column
    scored = df.dropna(subset=["pred"])
    return (scored["pred"] == scored["label"]).mean(), len(scored), df["pred"].isna().sum()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)                      # qwen, mistral, llama, llama_scout
    p.add_argument("--prompt", default="base", choices=["base", "lang", "base_eg", "lang_eg"])
    p.add_argument("--lang", nargs="*", default=LANGS)
    p.add_argument("--labels_csv", default="results/ethics_dataset.csv")
    args = p.parse_args()

    truth = pd.read_csv(args.labels_csv)[["input_id", "label"]]

    rows = []
    for lang in args.lang:
        path = f"results/{args.model}/eval_{lang}_{args.model}_{args.prompt}.csv"
        try:
            acc, n, bad = accuracy(path, truth)
        except FileNotFoundError:
            print(f"[skip] {lang}: {path} not found")
            continue
        rows.append({"language": lang, "accuracy": round(acc, 4), "n_scored": n, "n_unparsed": bad})

    print(pd.DataFrame(rows).to_string(index=False))