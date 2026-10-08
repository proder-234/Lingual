# Multilingual ETHICS Evaluation -- Utilitarianism

Evaluates LLMs on the **utilitarianism** subset of the
[ETHICS benchmark](https://huggingface.co/datasets/hendrycks/ethics), machine-translated out of
English, to see whether a model judges the same item differently depending on the language it is
presented in. Each ETHICS category lives on its own branch of this repo; this is the `utilitarianism` branch.

**Label:** The model gives `0` to the **more** ethical of two scenarios and `1` to the less ethical one (exactly one of each), from a utilitarian standpoint. `label` is **Scenario 2's value**.

See [`RUNNING.md`](RUNNING.md) for the exact command sequence for this category.

## Directory structure

```
.
├── translate.py             # English -> hi ne de zh es fr with NLLB-200 3.3B
├── inference.py             # runs one model x language x prompt style, resumable
├── metrics.py               # accuracy / F1 / balanced accuracy per language
├── toxicity.py              # Detoxify toxicity scores for the justifications
├── mismatch.py              # legacy, see "Known gaps"
├── prompts/
│   ├── base_prompt.py       # English instructions, scenario in the target language
│   ├── base_examples.py     # same + 32 labelled examples
│   ├── lang_prompt.py       # instructions fully in the target language
│   ├── lang_examples.py     # same + 32 examples in the target language
│   └── lang.py              # language codes / names
├── models/
│   ├── models.py            # model registry, response parsing (clean / parse)
│   ├── mistral.py           # Mistral-7B-Instruct-v0.2 via transformers (GPU)
│   ├── llama.py             # Llama 3.1 8B via Ollama
│   ├── llama_scout.py       # Llama 4 Scout via Ollama
│   └── qwen.py              # Qwen3-8B (4-bit) via mlx_lm, Apple Silicon only
├── results/                 # datasets and all outputs
├── RUNNING.md               # step-by-step commands for this category
└── requirements.txt
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- `mistral` needs `HUGGINGFACE_API_KEY` in a `.env` file at the project root.
- `llama` and `llama_scout` need an [Ollama](https://ollama.com) server with the model pulled
  (`ollama pull llama3.1:8b`, `ollama pull llama4:scout`).
- `qwen` uses `mlx_lm` and only runs on Apple Silicon.
- `toxicity.py` additionally needs `pip install detoxify`.

You only need the backends for the models you plan to run.

## Data

There is no loading step.

All data is in one file, `results/ethics_dataset.csv` (22,818 rows), with columns
`split, input_id, Scenario1, Scenario2, label`:

| `split` | Rows | Use |
|---|---|---|
| `util_train` | 13,738 | **do not evaluate** -- the few-shot examples are drawn from it (14 of the 32 appear verbatim) |
| `util_test` | 4,808 | evaluate |
| `util_test_hard` | 4,272 | evaluate (harder pairs) |

`input_id` is the row number within its split -- the same id the translated files and the evaluation
outputs use -- so a row is identified by `split` + `input_id`.

## Translation

`translate.py` translates every text field into all target languages (`hi ne de zh es fr`). Two text fields, translated separately: `en_Scenario1, en_Scenario2, hi_Scenario1, ...`. `--split` picks one split from `results/ethics_dataset.csv` (the default `--input_csv`); translate each test split on its own:

```bash
python translate.py --split util_test      --output_csv results/util_test_translated.csv
python translate.py --split util_test_hard --output_csv results/util_test_hard_translated.csv
```

Useful flags: `--langs hi ne` (subset of languages), `--append` (add/replace only those languages in
an existing output file), `--batch_size N` (lower it if the GPU runs out of memory), `--qc` (adds
length-ratio and number-match quality columns). The file is saved after every language.

## Inference

```bash
python inference.py --input_csv results/util_test_translated.csv --lang hi --model llama_scout --prompt lang_eg --limit 0
```

- `--model`: `mistral`, `llama`, `llama_scout`, `qwen`
- `--lang`: `en hi ne de zh es fr`
- `--prompt`: `base` / `lang` (no examples), `base_eg` / `lang_eg` (with 32 examples).
  **English is run with `base` and `base_eg` only.**
- `--limit N`: at most N new scenarios per run (default 300); `--limit 0` = everything left.

Any of `--lang`, `--model`, `--prompt` left out is asked for interactively. The model sees both scenarios and answers `scenario_1:` and `scenario_2:`. `response` is Scenario 2's value, or `None` when a line is missing or both scenarios got the same value.

Output: `results/<split>/<model>/eval_<lang>_<model>_<prompt>.csv`, where `<split>` is `util_test` or `util_test_hard` (taken from the `--input_csv` name), one row per scenario (`input_id, output`). Runs are **resumable**: scenarios already in
the output file are skipped, so re-running the same command continues where it stopped.

Each `output` holds the input, `response: 0/1` and the model's `justification`. If no clear 0/1 can be
read from the model's answer, `response` is `None`; generation is greedy (temperature 0), so
re-running such a row gives the same result.

## Metrics

```bash
python metrics.py --split util_test --model llama_scout --prompt lang_eg
```

Prints, per language: `accuracy` (parsed rows only), `accuracy_all` (unparsed `None` rows count as
wrong), `f1` (class 1), `balanced_acc`, `n_scored`, `n_unparsed`, plus `grouped_em` / `n_groups` for
virtue. `--lang` restricts the languages.

Always pass `--input_csv results/<split>_translated.csv` to `inference.py`, and `--split <split>` to `metrics.py`; test and test-hard are reported separately.

## Toxicity

```bash
python toxicity.py --pattern "results/mistral/eval_*.csv"
```

Writes a `*_tox.csv` copy of each matching file with Detoxify (multilingual) scores for the
justification; the original files are not modified.

## Known gaps

- `mismatch.py` still reads the old `result/eval_<lang>.csv` layout and has no command-line options;
  it does not work with the current `results/<model>/...` outputs.
