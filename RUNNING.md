# Justice: how to run

**Label:** `1` = the action or claim is just and reasonable, `0` = unjust / unreasonable (the dataset's own label).
The model sees one scenario. Same layout as commonsense: `input_id, input, label` -> `en_text, hi_text, ...`.

Run every command from inside this folder.

```bash
python load_dataset.py        # justice test split -> results/ethics_dataset.csv (input_id, input, label)
python translate.py           # NLLB-200 3.3B -> results/ethics_translated.csv (en_text, hi_text, ne_text, ...)
python inference.py --lang hi --model llama_scout --prompt lang_eg --limit 0
python metrics.py --model llama_scout --prompt lang_eg
```

All runs for one model (en x {base, base_eg}; hi ne de zh es fr x {base, lang, base_eg, lang_eg}):
```bash
for lang in en hi ne de zh es fr; do
  for p in base base_eg lang lang_eg; do
    [ $lang = en ] && [[ $p == lang* ]] && continue      # English: base and base_eg only
    python inference.py --lang $lang --model llama_scout --prompt $p --limit 0 
  done
done
```
Outputs: `results/<model>/eval_<lang>_<model>_<prompt>.csv` (columns `input_id, output`).
