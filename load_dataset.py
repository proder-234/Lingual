import pandas as pd

def load_ethics_deontology(n=None, seed=42):
    url = "https://huggingface.co/datasets/hendrycks/ethics/resolve/refs%2Fconvert%2Fparquet/deontology/test/0000.parquet"
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
    df = load_ethics_deontology(n=None)
    df.to_csv("results/ethics_dataset.csv", index=False)
    print(f"Saved {len(df)} scenarios")
