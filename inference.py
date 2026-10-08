import argparse
import csv
import os
import re

from prompts.base_prompt import generate_prompt as base_generate_prompt
from prompts.lang_prompt import (
    LANG_COL,
    LANG_NAME,
    generate_prompt as lang_generate_prompt,
)
from prompts.base_examples import generate_prompt as base_eg_generate_prompt
from prompts.lang_examples import generate_prompt as lang_eg_generate_prompt
from models.models import AVAILABLE_MODELS, get_query_model

PROMPT_TYPES = ["base", "lang", "base_eg", "lang_eg"]
DEFAULT_LIMIT = 300  # scenarios per run; --limit 0 = everything left


def build_prompt(prompt_type, scenario, lang_code):
    """base -> prompts/base_prompt.py, lang -> prompts/lang_prompt.py,
    base_eg -> prompts/base_examples.py, lang_eg -> prompts/lang_examples.py."""
    if prompt_type == "lang":
        return lang_generate_prompt(scenario, lang_code)
    if prompt_type == "lang_eg":
        return lang_eg_generate_prompt(scenario, lang_code)
    target_language = LANG_NAME.get(lang_code, lang_code)
    if prompt_type == "base_eg":
        return base_eg_generate_prompt(scenario, target_language)
    return base_generate_prompt(scenario, target_language)


# Two-field layouts: (first column, second column, how they are joined on the output's "input:" line).
#   deontology -> (scenario, excuse), virtue -> (scenario, trait), utilitarianism -> (Scenario1, Scenario2)
PAIRS = [
    ("scenario", "excuse", " "),
    ("scenario", "trait", " [SEP] "),
    ("Scenario1", "Scenario2", " [SEP] "),
]


def get_scenario(row, lang):
    """Returns (input for the prompt, one-line text for the output CSV, is_utilitarian_pair).
    Uses a two-field pair when the translated file has those columns; otherwise the single
    <lang>_text column (old layout)."""
    for first, second, joiner in PAIRS:
        a, b = f"{lang}_{first}", f"{lang}_{second}"
        if a in row and b in row:
            return (row[a], row[b]), f"{row[a]}{joiner}{row[b]}", first == "Scenario1"
    text = row[LANG_COL[lang]]
    return text, text, False


_S1 = re.compile(r"scenario[\s_]*1\s*\**\s*[:：]\s*\**\s*\[?\s*([01])\b", re.IGNORECASE)
_S2 = re.compile(r"scenario[\s_]*2\s*\**\s*[:：]\s*\**\s*\[?\s*([01])\b", re.IGNORECASE)


def parse_pair(full_response):
    """Utilitarianism: read 'scenario_1: x' and 'scenario_2: y' (0 = more ethical, 1 = less ethical).
    Returns (s1, s2, score) where score = Scenario 2's value (matches the dataset label),
    or None when either line is missing or both scenarios got the same value."""
    m1, m2 = _S1.search(full_response or ""), _S2.search(full_response or "")
    s1 = int(m1.group(1)) if m1 else None
    s2 = int(m2.group(1)) if m2 else None
    score = s2 if (s1 is not None and s2 is not None and s1 != s2) else None
    return s1, s2, score


def ask(question, choices):
    choices_str = "/".join(choices)
    while True:
        answer = input(f"{question} [{choices_str}]: ").strip().lower()
        if answer in choices:
            return answer
        print(f"Please choose one of: {choices_str}")


def load_done_ids(output_csv):
    """input_ids already in the output file (empty set if there is no file yet)."""
    if not os.path.exists(output_csv) or os.path.getsize(output_csv) == 0:
        return set()
    with open(output_csv, newline="", encoding="utf-8") as f:
        return {r["input_id"] for r in csv.DictReader(f) if r.get("input_id")}


def run(input_csv, output_csv, lang, model_name, prompt_type, limit):
    with open(input_csv, newline="", encoding="utf-8") as f_in:
        rows = list(csv.DictReader(f_in))

    # Resume: skip rows already saved for this model / language / prompt.
    done_ids = load_done_ids(output_csv)
    pending = [r for r in rows if r["input_id"] not in done_ids]
    print(f"Output file: {output_csv}")
    print(f"Total: {len(rows)} | done: {len(done_ids)} | remaining: {len(pending)}")

    if not pending:
        print("Nothing left to do.")
        return

    batch = pending[:limit] if limit else pending
    query_model = get_query_model(model_name)

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    write_header = not os.path.exists(output_csv) or os.path.getsize(output_csv) == 0

    with open(output_csv, "a", newline="", encoding="utf-8") as f_out:  # append: keeps earlier results
        writer = csv.DictWriter(f_out, fieldnames=["input_id", "output"])
        if write_header:
            writer.writeheader()

        for i, row in enumerate(batch, 1):
            prompt_input, input_text, is_pair = get_scenario(row, lang)
            prompt = build_prompt(prompt_type, prompt_input, lang)

            print(f"[{i}/{len(batch)} | overall {len(done_ids) + i}/{len(rows)}] generating...", end=" ", flush=True)
            full_response, score, justification = query_model(prompt)

            if is_pair:
                # Utilitarianism: the model labels both scenarios; "response" = Scenario 2's label.
                s1, s2, score = parse_pair(full_response)
                output = (f"input: {input_text}\nscenario_1: {s1}\nscenario_2: {s2}\n"
                          f"response: {score}\njustification: {justification}")
            else:
                output = f"input: {input_text}\nresponse: {score}\njustification: {justification}"

            writer.writerow({"input_id": row["input_id"], "output": output})
            f_out.flush()
            os.fsync(f_out.fileno())

            print(f"response={score}" if score is not None else "[!] could not parse a clean 0/1 response")

    left = len(pending) - len(batch)
    if left:
        print(f"{left} remaining -- run the same command again to continue.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run inference over translated scenarios with a chosen model and prompt style."
    )
    parser.add_argument("--input_csv", default="results/ethics_translated.csv")
    parser.add_argument("--output_csv", default=None,
                        help="Defaults to results/<model>/eval_<lang>_<model>_<prompt>.csv")
    parser.add_argument("--lang", choices=list(LANG_COL.keys()), default=None)
    parser.add_argument("--model", choices=AVAILABLE_MODELS, default=None)
    parser.add_argument(
        "--prompt",
        choices=PROMPT_TYPES,
        default=None,
        help="base / lang = without examples; base_eg / lang_eg = with the 32 examples",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Max scenarios per run (default {DEFAULT_LIMIT}; 0 = all remaining)")
    args = parser.parse_args()

    lang = args.lang or ask("Which language do you want to run inference on?", list(LANG_COL.keys()))
    model_name = args.model or ask("Which model do you want to use?", AVAILABLE_MODELS)
    prompt_type = args.prompt or ask("Which prompt style do you want to use?", PROMPT_TYPES)

    # One folder per model, same layout metrics.py and mismatch.py read from.
    output_csv = args.output_csv or f"results/{model_name}/eval_{lang}_{model_name}_{prompt_type}.csv"

    run(args.input_csv, output_csv, lang, model_name, prompt_type, args.limit)
    print("Done.")