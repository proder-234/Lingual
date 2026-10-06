import argparse
import re

import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

MODEL = "facebook/nllb-200-1.3B"

# Language registry -- ADD NEW LANGUAGES HERE.
#   key = short code used across the project, col = column in ethics_translated.csv,
#   nllb = NLLB-200 code (https://github.com/facebookresearch/flores/blob/main/flores200/README.md)
# A new language also needs entries in prompts/lang_prompt.py (LANG_NAME / LOCALIZED)
# and prompts/base_prompt.py (LANG_COL) -- see README.md -> "Adding a new language".
LANGUAGES = {
    "hi": {"col": "hi_text", "nllb": "hin_Deva"},
    "ne": {"col": "ne_text", "nllb": "npi_Deva"},
    "de": {"col": "de_text", "nllb": "deu_Latn"},
    "zh": {"col": "zh_text", "nllb": "zho_Hans"},
    "es": {"col": "es_text", "nllb": "spa_Latn"},
    "fr": {"col": "fr_text", "nllb": "fra_Latn"},
}

device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Loading NLLB model on {device}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL).to(device).eval()
print("Model ready!")


def strip_forum_tags(text):
    """Remove leading Reddit tags (AITA, WIBTA, ...)."""
    return re.sub(r"^(AITA|WIBTA|Aitah?)\b[:\-\|]?\s*", "", str(text), flags=re.IGNORECASE).strip()


def split_text(text, max_tokens=400):
    """Split a long scenario into chunks of at most max_tokens tokens."""
    fits = lambda s: len(tokenizer.encode(s)) <= max_tokens
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        test = (current + " " + sentence).strip()
        if fits(test):
            current = test
            continue
        if current:
            chunks.append(current)
        current = ""
        for word in sentence.split():  # very long single sentence: split by words
            test = (current + " " + word).strip()
            if fits(test):
                current = test
            else:
                if current:
                    chunks.append(current)
                current = word
    if current:
        chunks.append(current)
    return chunks


def translate_batch(batch, src_lang, tgt_lang):
    tokenizer.src_lang = src_lang
    inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=False).to(device)
    with torch.no_grad():
        output = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids(tgt_lang),
            max_length=250,
            num_beams=1,
        )
    return tokenizer.batch_decode(output, skip_special_tokens=True)


def translate_multi(texts, src_lang, tgt_langs, batch_size=8):
    """tgt_langs: {output_key: nllb_code}. Returns {output_key: [translation, ...]} aligned to texts.
    Each row is split into chunks once, however many target languages there are."""
    results = {key: [] for key in tgt_langs}
    for index, text in enumerate(texts):
        print(f"Translating {index + 1}/{len(texts)}...", flush=True)
        chunks = split_text(str(text).strip())
        for key, tgt_lang in tgt_langs.items():
            translated = [
                t
                for i in range(0, len(chunks), batch_size)
                for t in translate_batch(chunks[i:i + batch_size], src_lang, tgt_lang)
            ]
            results[key].append(" ".join(translated))
    return results


def main():
    parser = argparse.ArgumentParser(description="Translate English scenarios into one or more target languages.")
    parser.add_argument("--input_csv", default="results/ethics_dataset.csv")
    parser.add_argument("--output_csv", default="results/ethics_translated.csv")
    parser.add_argument("--langs", nargs="+", choices=list(LANGUAGES), default=list(LANGUAGES),
                        help="Target language code(s) to translate into (space-separated).")
    parser.add_argument("--src_lang", default="eng_Latn")
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--append", action="store_true",
                        help="Load --output_csv if it exists and add/replace only the columns "
                             "for --langs, keeping all other existing translations.")
    args = parser.parse_args()

    if args.append:
        print(f"Append mode: reading existing {args.output_csv}...")
        df = pd.read_csv(args.output_csv)
    else:
        print("Reading input CSV...")
        df = pd.read_csv(args.input_csv).rename(columns={"input": "en_text"})
        df["en_text"] = df["en_text"].apply(strip_forum_tags)
    print(f"Loaded {len(df)} rows.")

    tgt_langs = {LANGUAGES[c]["col"]: LANGUAGES[c]["nllb"] for c in args.langs}
    print(f"Translating English -> {', '.join(args.langs)}...")
    translations = translate_multi(df["en_text"].tolist(), args.src_lang, tgt_langs, args.batch_size)
    for c in args.langs:
        col = LANGUAGES[c]["col"]
        df[col] = translations[col]

    df.to_csv(args.output_csv, index=False)
    print(f"Done!\nSaved to {args.output_csv}")


if __name__ == "__main__":
    main()
