import pandas as pd

# Hugging Face names the ETHICS test split "validation" and test_hard "test".
HF_SPLIT = {"t": "validation", "th": "test"}


def load_ethics_deontology(n=None, seed=42, split="th"):
    url = f"https://huggingface.co/datasets/hendrycks/ethics/resolve/refs%2Fconvert%2Fparquet/deontology/{HF_SPLIT[split]}/0000.parquet"
    df = pd.read_parquet(url)

    # Keep scenario and excuse as two separate fields: they are translated separately
    # and shown to the model as "Scenario: ..." / "Excuse: ...", like the 32 examples.
    df = df[["scenario", "excuse", "label"]].dropna()
    df["scenario"] = df["scenario"].str.strip()
    df["excuse"] = df["excuse"].str.strip()

    if n is not None:
        df = df.sample(n=min(n, len(df)), random_state=seed).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    df["label"] = df["label"].astype(int)          # 1 = reasonable excuse, 0 = unreasonable
    df = df[["scenario", "excuse", "label"]]
    df.insert(0, "input_id", range(len(df)))
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=["t", "th"], help="t = test, th = test_hard")
    split = ap.parse_args().split
    df = load_ethics_deontology(n=None, split=split)
    df.to_csv(f"results/ethics_dataset_{split}.csv", index=False)
    print(f"Saved {len(df)} scenarios")
