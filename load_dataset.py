import pandas as pd

# The ETHICS utilitarianism CSVs with a label column (Hugging Face only has baseline / less_pleasant pairs).
# t = test, th = test_hard.
SOURCE = {"t": "/home/mkj82/util_test_modified.csv", "th": "/home/mkj82/util_test_hard_modified.csv"}


def load_ethics_utilitarianism(n=None, seed=42, split="th"):
    df = pd.read_csv(SOURCE[split])

    # Scenario1 and Scenario2 stay separate fields: they are translated separately.
    df = df[["Scenario1", "Scenario2", "label"]].dropna()

    if n is not None:
        df = df.sample(n=min(n, len(df)), random_state=seed).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    df["label"] = df["label"].astype(int)          # Scenario 2's value: 0 = more ethical, 1 = less ethical
    df.insert(0, "input_id", range(len(df)))
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=["t", "th"], help="t = test, th = test_hard")
    split = ap.parse_args().split
    df = load_ethics_utilitarianism(n=None, split=split)
    df.to_csv(f"results/ethics_dataset_{split}.csv", index=False)
    print(f"Saved {len(df)} scenarios")
