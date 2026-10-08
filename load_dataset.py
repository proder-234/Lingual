import pandas as pd

def load_ethics_virtue(n=None, seed=42):
    url = "https://huggingface.co/datasets/hendrycks/ethics/resolve/refs%2Fconvert%2Fparquet/virtue/test/0000.parquet"
    df = pd.read_parquet(url)

    # Each row is "<sentence> [SEP] <trait>". Keep the two parts as separate fields: they are
    # translated separately and shown to the model as "Scenario: ..." / "Trait: ...".
    df = df[["scenario", "label"]].dropna()
    parts = df["scenario"].str.split("[SEP]", n=1, expand=True, regex=False)
    df["scenario"] = parts[0].str.strip()
    df["trait"] = parts[1].str.strip()

    if n is not None:
        df = df.sample(n=min(n, len(df)), random_state=seed).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    df["label"] = df["label"].astype(int)          # 1 = the trait fits the behaviour, 0 = it does not
    df = df[["scenario", "trait", "label"]]
    df.insert(0, "input_id", range(len(df)))
    return df


if __name__ == "__main__":
    df = load_ethics_virtue(n=None)
    df.to_csv("results/ethics_dataset.csv", index=False)
    print(f"Saved {len(df)} scenarios")
