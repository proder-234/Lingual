"""Find and re-translate broken NLLB translations in every ethics category.

A translated cell is flagged when it shows one of these NLLB failure modes:
  bracket    - text in brackets that isn't in the English, e.g. Nepali "[पृष्ठ २३-मा भएको चित्र]"
               ("[picture on page 23]") replacing a sentence
  dropped    - English has 2+ sentences, the translation has fewer AND is unusually short
  truncated  - translation far shorter than usual for the language (cut off)
  runaway    - translation far longer than usual, or a phrase repeated 3+ times (looping)
  empty / untranslated - nothing, or the English text copied unchanged
Flagged cells are re-translated one sentence at a time (sentences are never merged), with the
category's original NLLB model and beam setting, no output-length cap, and "[" / "]" banned.
The new text is kept only if it fixes the flags; otherwise the old text stays and the cell is
listed as unresolved.

    python3 fix_translations.py --dry-run          # only count flagged cells
    NLLB_FP16=1 python3 fix_translations.py        # fix all categories

For each category writes results/ethics_translated.csv in place and
results/retranslated_cells.csv (input_id, lang, field, flags, en, old, new, status).
"""
import argparse
import csv
import os
import re
import statistics
from collections import Counter

DESKTOP = os.path.expanduser("~/Desktop")
# category -> (checkout, NLLB model used originally, num_beams used originally)
CATEGORIES = {
    "commonsense": ("TXST-Multilingual", "facebook/nllb-200-1.3B", 1),
    "justice": ("Lingual-justice", "facebook/nllb-200-3.3B", 4),
    "virtue": ("Lingual-virtue", "facebook/nllb-200-3.3B", 4),
    "deontology": ("Lingual-deontology", "facebook/nllb-200-3.3B", 4),
    "utilitarianism": ("Lingual-utilitarianism", "facebook/nllb-200-3.3B", 4),
}
NLLB = {"hi": "hin_Deva", "ne": "npi_Deva", "de": "deu_Latn", "zh": "zho_Hans", "es": "spa_Latn", "fr": "fra_Latn"}
END = re.compile(r"[.!?。！？।]+")
SPLIT = re.compile(r"(?<=[.!?])\s+")


def n_sentences(text):
    return len([s for s in END.split(str(text).strip()) if s.strip()])


def repeated(text, lang):
    """A phrase occurring 3+ times: word 3-grams (char 4-grams for Chinese)."""
    units = list(text.replace(" ", "")) if lang == "zh" else text.lower().split()
    n = 4 if lang == "zh" else 3
    grams = Counter(tuple(units[i:i + n]) for i in range(len(units) - n + 1))
    return any(c >= 3 for c in grams.values())


def flags(en, tr, lang, med):
    en, tr = str(en).strip(), str(tr).strip()
    out = []
    if not tr:
        return ["empty"]
    if len(en) > 15 and tr == en:
        out.append("untranslated")
    if ("[" in tr or "पृष्ठ" in tr) and "[" not in en:
        out.append("bracket")
    if len(en) >= 20:
        ratio = len(tr) / len(en)
        if n_sentences(en) >= 2 and n_sentences(tr) < n_sentences(en) and ratio < 0.75 * med:
            out.append("dropped")
        elif ratio < 0.5 * med:
            out.append("truncated")
        if ratio > 2.0 * med or (repeated(tr, lang) and not repeated(en, "en")):
            out.append("runaway")
    return out


def text_fields(header):
    return [c[3:] for c in header if c.startswith("en_")]


def scan(rows, fields):
    """{(row_index, lang, field): [flags]} plus the per-column median length ratios."""
    found, medians = {}, {}
    for lang in NLLB:
        for field in fields:
            en_col, tr_col = f"en_{field}", f"{lang}_{field}"
            ratios = [len(r[tr_col]) / len(r[en_col]) for r in rows if len(r[en_col]) >= 20]
            med = statistics.median(ratios) if ratios else 1.0
            medians[(lang, field)] = med
            for i, r in enumerate(rows):
                f = flags(r[en_col], r[tr_col], lang, med)
                if f:
                    found[(i, lang, field)] = f
    return found, medians


class Translator:
    def __init__(self, model_name, num_beams):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" or os.environ.get("NLLB_FP16") == "1" else torch.float32
        print(f"Loading {model_name} ({dtype}) on {self.device}...", flush=True)
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name, dtype=dtype).to(self.device).eval()
        self.num_beams = num_beams
        vocab = self.tok.get_vocab()
        self.bad_words = [[i] for t, i in vocab.items() if "[" in t or "]" in t]

    def sentences(self, text, max_tokens=128):
        """One chunk per sentence; a sentence over max_tokens is split by words."""
        chunks = []
        for s in SPLIT.split(str(text).strip()):
            if not s:
                continue
            if len(self.tok.encode(s)) <= max_tokens:
                chunks.append(s)
                continue
            cur = ""
            for w in s.split():
                if len(self.tok.encode((cur + " " + w).strip())) <= max_tokens:
                    cur = (cur + " " + w).strip()
                else:
                    if cur:
                        chunks.append(cur)
                    cur = w
            if cur:
                chunks.append(cur)
        return chunks

    def translate(self, texts, lang, batch_size=32, no_repeat=0):
        self.tok.src_lang = "eng_Latn"
        chunked = {t: self.sentences(t) for t in dict.fromkeys(texts)}
        flat = sorted({c for cs in chunked.values() for c in cs}, key=len)
        done = {}
        for s in range(0, len(flat), batch_size):
            batch = flat[s:s + batch_size]
            inputs = self.tok(batch, return_tensors="pt", padding=True).to(self.device)
            with self.torch.no_grad():
                out = self.model.generate(
                    **inputs,
                    forced_bos_token_id=self.tok.convert_tokens_to_ids(NLLB[lang]),
                    max_new_tokens=int(inputs["input_ids"].shape[1] * 1.6) + 10,
                    num_beams=self.num_beams,
                    bad_words_ids=self.bad_words,
                    no_repeat_ngram_size=no_repeat,
                )
            for src, tgt in zip(batch, self.tok.batch_decode(out, skip_special_tokens=True)):
                done[src] = tgt
        return [" ".join(done[c] for c in chunked[t]) for t in texts]


def fix_category(name, dry_run):
    folder, model_name, beams = CATEGORIES[name]
    path = os.path.join(DESKTOP, folder, "results", "ethics_translated.csv")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    fields = text_fields(header)
    found, medians = scan(rows, fields)

    kinds = Counter(k for fl in found.values() for k in fl)
    by_lang = Counter(lang for _, lang, _ in found)
    print(f"\n== {name}: {len(found)} flagged cells in {len({i for i, _, _ in found})} rows "
          f"| {dict(kinds)} | {dict(by_lang)}", flush=True)
    if dry_run or not found:
        return

    tr = Translator(model_name, beams)
    log = []
    for lang in NLLB:
        for field in fields:
            cells = [i for (i, l, f) in found if l == lang and f == field]
            if not cells:
                continue
            en = [rows[i][f"en_{field}"] for i in cells]
            new = tr.translate(en, lang)
            # still looping? one more try with repeated 4-grams blocked
            retry = [k for k, (e, t) in enumerate(zip(en, new)) if "runaway" in flags(e, t, lang, medians[(lang, field)])]
            if retry:
                again = tr.translate([en[k] for k in retry], lang, no_repeat=4)
                for k, t in zip(retry, again):
                    new[k] = t
            fixed = 0
            for i, e, t in zip(cells, en, new):
                old = rows[i][f"{lang}_{field}"]
                before, after = found[(i, lang, field)], flags(e, t, lang, medians[(lang, field)])
                ok = len(after) < len(before)
                if ok:
                    rows[i][f"{lang}_{field}"] = t
                    fixed += 1
                log.append({"input_id": rows[i]["input_id"], "lang": lang, "field": field,
                            "flags": "+".join(before), "en": e, "old": old, "new": t,
                            "status": "fixed" if not after else ("improved" if ok else "unresolved")})
            print(f"  {lang} {field}: {fixed}/{len(cells)} cells replaced", flush=True)

    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

    log_path = os.path.join(DESKTOP, folder, "results", "retranslated_cells.csv")
    prev = []
    if os.path.exists(log_path):
        with open(log_path, newline="", encoding="utf-8") as f:
            prev = list(csv.DictReader(f))
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        cols = ["input_id", "lang", "field", "flags", "en", "old", "new", "status"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in prev:  # keep the earlier utilitarianism log, marked as such
            p.setdefault("flags", "dropped (earlier pass)")
            p.setdefault("status", "fixed")
            w.writerow(p)
        w.writerows(log)
    status = Counter(x["status"] for x in log)
    print(f"  {name} done: {dict(status)}", flush=True)
    del tr


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--categories", nargs="+", default=list(CATEGORIES), choices=list(CATEGORIES))
    args = ap.parse_args()
    for c in args.categories:
        fix_category(c, args.dry_run)
