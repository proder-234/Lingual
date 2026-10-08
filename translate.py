import argparse
import re

import pandas as pd
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from transformers import logging as hf_logging

MODEL = "facebook/nllb-200-3.3B"   # alternatives: "facebook/nllb-200-distilled-1.3B", "facebook/nllb-200-1.3B"

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

CHUNK_TOKENS = 128        # NLLB is sentence-level; small chunks hallucinate/truncate far less
NUM_BEAMS = 4
NO_REPEAT_NGRAM = 0       # 0 = off. It runs on CPU and slows beam search a lot; chunks are short so loops are rare.
                          # Set to 4 if the --qc ratio flags show repeated/looping output.

device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32   # fp16 only on CUDA
print(f"Loading NLLB model on {device}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, dtype=dtype).to(device).eval()
hf_logging.set_verbosity_error()   # hides the harmless "max_new_tokens and max_length both set" warning on every batch
print("Model ready!")


# --------------------------------------------------------------------------
# Text prep
# --------------------------------------------------------------------------
def strip_forum_tags(text):
    """Remove leading Reddit tags (AITA, WIBTA, ...)."""
    return re.sub(r"^(AITA|WIBTA|Aitah?)\b[:\-\|]?\s*", "", str(text), flags=re.IGNORECASE).strip()


def split_text(text, max_tokens=CHUNK_TOKENS):
    """Split a scenario into chunks of at most max_tokens tokens (sentence-aligned where possible)."""
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


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------
def translate_batch(batch, src_lang, tgt_lang):
    tokenizer.src_lang = src_lang
    inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=False).to(device)
    longest = inputs["input_ids"].shape[1]
    with torch.no_grad():
        output = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids(tgt_lang),
            max_new_tokens=int(longest * 1.6) + 10,   # scales with input: no silent cut-off
            num_beams=NUM_BEAMS,                      # greedy hallucinates more
            no_repeat_ngram_size=NO_REPEAT_NGRAM,     # stops looping repetition
        )
    return tokenizer.batch_decode(output, skip_special_tokens=True)


def translate_one_lang(texts, src_lang, tgt_lang, batch_size=32, desc=None):
    """Dedup -> chunk -> flatten -> sort by length -> batch across rows -> reassemble.
    Returns a list aligned to `texts`."""
    texts = [str(t).strip() for t in texts]
    tokenizer.src_lang = src_lang
    chunked = {u: split_text(u) for u in dict.fromkeys(texts)}          # unique texts only
    flat = [(u, i, c) for u, cs in chunked.items() for i, c in enumerate(cs)]
    flat.sort(key=lambda x: len(x[2]))                                  # similar lengths -> less padding

    done = {}
    for s in tqdm(range(0, len(flat), batch_size), desc=desc or tgt_lang):
        batch = flat[s:s + batch_size]
        outs = translate_batch([c for _, _, c in batch], src_lang, tgt_lang)
        for (u, i, _), out in zip(batch, outs):
            done[(u, i)] = out

    return [" ".join(done[(u, i)] for i in range(len(chunked[u]))) for u in texts]


# --------------------------------------------------------------------------
# Quality checks (soft flags -- inspect flagged rows, don't trust blindly)
# --------------------------------------------------------------------------
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_match(en, tr):
    return set(_NUM_RE.findall(str(en))) == set(_NUM_RE.findall(str(tr)))


# Text columns translate.py looks for in the loader's output, in order.
TEXT_FIELDS = ["scenario", "excuse", "trait", "Scenario1", "Scenario2"]


def col_name(lang_code, field):
    """Column holding `field` in `lang_code`.
    field "input" keeps the old names (en_text, hi_text, ...); any other field -> <lang>_<field>,
    e.g. en_scenario, hi_scenario, en_excuse, hi_excuse."""
    if field == "input":
        return "en_text" if lang_code == "en" else LANGUAGES[lang_code]["col"]
    return f"{lang_code}_{field}"


def add_qc(df, langs, fields, use_labse=False):
    """For every translated column adds <col>_ratio, <col>_ratio_flag, <col>_nums_ok
    (and <col>_sim, <col>_sim_flag with LaBSE)."""
    labse = util = None
    if use_labse:
        from sentence_transformers import SentenceTransformer, util
        labse = SentenceTransformer("sentence-transformers/LaBSE")

    for field in fields:
        src = df[col_name("en", field)].astype(str)
        en_emb = labse.encode(src.tolist(), batch_size=64, convert_to_tensor=True) if labse else None

        for c in langs:
            col = col_name(c, field)
            tr = df[col].astype(str)

            # Length ratio relative to this language's own median (Chinese is much shorter in chars, etc.)
            ratio = tr.str.len() / src.str.len().clip(lower=1)
            med = ratio.median()
            df[f"{col}_ratio"] = ratio
            df[f"{col}_ratio_flag"] = (ratio < 0.5 * med) | (ratio > 2.0 * med)

            df[f"{col}_nums_ok"] = [numbers_match(e, t) for e, t in zip(src, tr)]

            msg = (f"[{col}] ratio flags: {int(df[f'{col}_ratio_flag'].sum())} | "
                   f"number mismatches: {int((~df[f'{col}_nums_ok']).sum())}")

            if labse is not None:
                tr_emb = labse.encode(tr.tolist(), batch_size=64, convert_to_tensor=True)
                sim = util.pairwise_cos_sim(en_emb, tr_emb).cpu().numpy()
                df[f"{col}_sim"] = sim
                low = pd.Series(sim).quantile(0.02)           # bottom 2% as a starting point; tune by hand
                df[f"{col}_sim_flag"] = sim < low
                msg += f" | LaBSE bottom-2% cutoff: {low:.3f}"
            print(msg)
    return df


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Translate English scenarios into one or more target languages.")
    parser.add_argument("--input_csv", default="results/ethics_dataset.csv")
    parser.add_argument("--output_csv", default="results/ethics_translated.csv")
    parser.add_argument("--split", default=None,
                        help="Only translate rows of this split (for an input with a `split` column, e.g. "
                             "utilitarianism: util_test or util_test_hard).")
    parser.add_argument("--langs", nargs="+", choices=list(LANGUAGES), default=list(LANGUAGES),
                        help="Target language code(s) to translate into (space-separated).")
    parser.add_argument("--fields", nargs="+", default=None,
                        help="Text column(s) of --input_csv to translate, each on its own. Default: "
                             "auto-detect (scenario + excuse for deontology, scenario + trait for virtue, "
                             "Scenario1 + Scenario2 for utilitarianism, otherwise the old single 'input' column).")
    parser.add_argument("--src_lang", default="eng_Latn")
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--append", action="store_true",
                        help="Load --output_csv if it exists and add/replace only the columns "
                             "for --langs, keeping all other existing translations.")
    parser.add_argument("--qc", action="store_true",
                        help="Add length-ratio and number-match quality columns after translating.")
    parser.add_argument("--labse", action="store_true",
                        help="With --qc, also add LaBSE cross-lingual similarity (needs sentence-transformers).")
    args = parser.parse_args()

    if args.append:
        print(f"Append mode: reading existing {args.output_csv}...")
        df = pd.read_csv(args.output_csv)
        if args.fields is None:
            args.fields = [c for c in TEXT_FIELDS if f"en_{c}" in df.columns] or ["input"]
    else:
        print("Reading input CSV...")
        df = pd.read_csv(args.input_csv)
        if "split" in df.columns:                     # utilitarianism: one file holding several splits
            if args.split is None:
                raise SystemExit(f"{args.input_csv} holds several splits {sorted(df['split'].unique())}; "
                                 "pick one with --split.")
            df = df[df["split"] == args.split].drop(columns="split").reset_index(drop=True)
            if df.empty:
                raise SystemExit(f"No rows with split == '{args.split}' in {args.input_csv}.")
        if "input_id" not in df.columns:              # inference.py needs it to resume runs
            df.insert(0, "input_id", range(len(df)))
        if args.fields is None:
            args.fields = [c for c in TEXT_FIELDS if c in df.columns] or ["input"]
        for field in args.fields:
            if field not in df.columns:
                raise SystemExit(f"Column '{field}' not in {args.input_csv}. Columns: {list(df.columns)}")
            # English copy of each field: en_scenario, en_excuse, ... The old single 'input' column is
            # renamed to en_text instead, so commonsense/justice keep exactly their old layout.
            src = field
            if field == "input":
                df = df.rename(columns={"input": "en_text"})
                src = "en_text"
            df[col_name("en", field)] = df[src].astype(str).apply(strip_forum_tags)
    print(f"Loaded {len(df)} rows; translating field(s): {', '.join(args.fields)}")

    for c in args.langs:
        for field in args.fields:
            col = col_name(c, field)
            print(f"Translating English -> {c} ({field})...")
            df[col] = translate_one_lang(df[col_name("en", field)].tolist(), args.src_lang,
                                         LANGUAGES[c]["nllb"], args.batch_size, desc=f"{c}:{field}")
        df.to_csv(args.output_csv, index=False)          # checkpoint after every language
        print(f"Saved {c} -> {args.output_csv}")

    if args.qc:
        print("Running quality checks...")
        df = add_qc(df, args.langs, args.fields, use_labse=args.labse)
        df.to_csv(args.output_csv, index=False)

    print(f"Done!\nSaved to {args.output_csv}")


if __name__ == "__main__":
    main()
