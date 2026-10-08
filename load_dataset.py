import pandas as pd

def load_ethics_justice(n=None, seed=42):
    url = "https://huggingface.co/datasets/hendrycks/ethics/resolve/refs%2Fconvert%2Fparquet/justice/test/0000.parquet"
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
    df = load_ethics_justice(n=None)
    df.to_csv("results/ethics_dataset.csv", index=False)
    print(f"Saved {len(df)} scenarios")
