import pandas as pd

# Hugging Face names the ETHICS test split "validation" and test_hard "test".
HF_SPLIT = {"t": "validation", "th": "test"}


def load_ethics_justice(n=None, seed=42, split="th"):
    url = f"https://huggingface.co/datasets/hendrycks/ethics/resolve/refs%2Fconvert%2Fparquet/justice/{HF_SPLIT[split]}/0000.parquet"
    df = pd.read_parquet(url)

    df = df[["scenario", "label"]].dropna().rename(columns={"scenario": "input"})  # same layout as commonsense

    if n is not None:
        df = df.sample(n=min(n, len(df)), random_state=seed).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    df["label"] = df["label"].astype(int)          # 1 = just/reasonable, 0 = unjust/unreasonable
    df.insert(0, "input_id", range(len(df)))
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=["t", "th"], help="t = test, th = test_hard")
    split = ap.parse_args().split
    df = load_ethics_justice(n=None, split=split)
    df.to_csv(f"results/ethics_dataset_{split}.csv", index=False)
    print(f"Saved {len(df)} scenarios")
