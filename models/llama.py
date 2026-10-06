import requests

from .models import clean, parse

OLLAMA_URL = "http://localhost:11434/api/generate"


def query_model(prompt, model_id="llama3.1:8b", max_new_tokens=220, temperature=0.0):
    prompt_with_prefill = prompt.rstrip() + "\nresponse: "

    def generate():
        data = {
            "model": model_id,
            "prompt": prompt_with_prefill,
            "stream": False,
            "options": {
                "num_predict": max_new_tokens,
                "temperature": temperature,
            },
        }

        response = requests.post(OLLAMA_URL, json=data)

        if response.status_code != 200:
            return f"Error: {response.status_code}"

        return response.json().get("response", "").strip()

    # First attempt
    raw = generate()
    full_response = clean(raw)

    score, justification = parse(
        "response: " + full_response,
        fallback="leading_digit",
    )

    # Retry once if no valid 0/1 response
    if score is None:
        raw = generate()
        full_response = clean(raw)

        score, justification = parse(
            "response: " + full_response,
            fallback="leading_digit",
        )

    return full_response, score, justification