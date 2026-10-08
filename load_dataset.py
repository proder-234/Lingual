import pandas as pd

BASE = "https://huggingface.co/datasets/hendrycks/ethics/resolve/refs%2Fconvert%2Fparquet"
TEXT_COL = {"commonsense": "input", "justice": "scenario", "virtue": "scenario"}


def load_ethics(subset="justice", split="test", n=None, seed=42):
    df = pd.read_parquet(f"{BASE}/{subset}/{split}/0000.parquet")
    df = df.rename(columns={TEXT_COL[subset]: "input"})  # keep downstream code unchanged

    if subset == "virtue":
        # scenario looks like "<sentence> [SEP] <trait>"
        parts = df["input"].str.split(r"\s*\[SEP\]\s*", n=1, expand=True)
        df["input"], df["trait"] = parts[0], parts[1]
        df = df[["input", "trait", "label"]]
    else:
        df = df[["input", "label"]]

    df = df.dropna()
    if n is not None:
        df = df.sample(n=min(n, len(df)), random_state=seed)
    df = df.reset_index(drop=True)

    df["label"] = df["label"].astype(int)
    df.insert(0, "input_id", range(len(df)))
    return df


if __name__ == "__main__":
    subset = "justice"  # or "virtue" / "commonsense"
    df = load_ethics(subset, n=None)
    df.to_csv(f"results/ethics_{subset}_dataset.csv", index=False)
    print(f"Saved {len(df)} scenarios")
