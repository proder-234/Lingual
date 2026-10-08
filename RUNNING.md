# Deontology: how to run

**Label:** `1` = the excuse is reasonable (it fits moral duties / ethical rules), `0` = unreasonable (the dataset's own label).
The model sees a scenario (a request such as "Could you...?" or a role such as "I am a personal trainer...")
and an excuse, as two labelled lines `Scenario:` / `Excuse:` (labels translated in lang / lang_eg).
The two fields stay separate columns and are translated separately.

Run every command from inside this folder.

```bash
python load_dataset.py        # deontology test split -> results/ethics_dataset.csv (input_id, scenario, excuse, label)
python translate.py           # -> results/ethics_translated.csv (en_scenario, en_excuse, hi_scenario, hi_excuse, ...)
python inference.py --lang hi --model llama_scout --prompt lang_eg --limit 0
python metrics.py --model llama_scout --prompt lang_eg
```

All runs for one model:
```bash
for lang in en hi ne de zh es fr; do
  for p in base base_eg lang lang_eg; do
    [ $lang = en ] && [[ $p == lang* ]] && continue      # English: base and base_eg only
    python inference.py --lang $lang --model llama_scout --prompt $p --limit 0 
  done
done
```
Outputs: `results/<model>/eval_<lang>_<model>_<prompt>.csv`; the `input:` line is `<scenario> <excuse>`.
