# Utilitarianism: how to run

**Label:** `label` = **Scenario 2's value**: `0` = Scenario 2 is the more ethical one, `1` = Scenario 2 is the less
ethical one (so `1` also means Scenario 1 is better). Labels are 50/50 in every file.
The model gives `0` to the more ethical scenario and `1` to the less ethical one (exactly one of each), from a
utilitarian standpoint (more overall well-being, less suffering for everyone affected).

There is **no loading step**. The data is in `results/`:

| File | Rows | Use |
|---|---|---|
| `util_train_modified.csv` | 13,738 | **do not evaluate**: the few-shot examples are drawn from it (14 of the 32 appear verbatim) |
| `util_test_modified.csv` | 4,808 | evaluate |
| `util_test_hard_modified.csv` | 4,272 | evaluate (harder pairs) |

`results/ethics_dataset.csv` (22,818 rows) holds all three files in one table with columns `split, input_id, Scenario1, Scenario2, label`. `split` is `util_train`, `util_test` or `util_test_hard`, and `input_id` is the row number within that split -- the same id the translated files and the evaluation outputs use -- so a row is identified by `split` + `input_id`. The pipeline itself still reads the three per-split files.

Run every command from inside this folder.

```bash
# 1. Translate each test file (Scenario1 and Scenario2 separately; adds input_id)
python translate.py --input_csv results/util_test_modified.csv      --output_csv results/util_test_translated.csv
python translate.py --input_csv results/util_test_hard_modified.csv --output_csv results/util_test_hard_translated.csv

# 2. Inference: the split folder is taken from the input file name
python inference.py --input_csv results/util_test_translated.csv --lang hi --model llama_scout --prompt lang_eg --limit 0
#   -> results/util_test/llama_scout/eval_hi_llama_scout_lang_eg.csv

# 3. Metrics, reported separately for test and test-hard
python metrics.py --split util_test      --model llama_scout --prompt lang_eg
python metrics.py --split util_test_hard --model llama_scout --prompt lang_eg
```

All runs for one model:
```bash
for split in util_test util_test_hard; do
  for lang in en hi ne de zh es fr; do
    for p in base base_eg lang lang_eg; do
      [ $lang = en ] && [[ $p == lang* ]] && continue      # English: base and base_eg only
      python inference.py --input_csv results/${split}_translated.csv --lang $lang --model llama_scout --prompt $p --limit 0
    done
  done
done
```

Output per row:
```
input: <Scenario1> [SEP] <Scenario2>
scenario_1: <0/1/None>
scenario_2: <0/1/None>
response: <Scenario 2's value, or None>
justification: <text>
```
`response` is compared directly with `label`. It is `None` (unparsed; counted as wrong in `accuracy_all`) when either
line is missing or both scenarios got the same value.
