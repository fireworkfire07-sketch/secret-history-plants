"""Groq (primary) / OpenRouter (fallback) JSON chat client for the v3 pipeline."""

from __future__ import annotations

import json
import os
import re
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _providers():
    out = []
    if os.environ.get("GROQ_API_KEY"):
        out.append((GROQ_URL, os.environ["GROQ_API_KEY"],
                    os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")))
    if os.environ.get("OPENROUTER_API_KEY"):
        out.append((OPENROUTER_URL, os.environ["OPENROUTER_API_KEY"],
                    os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")))
    if not out:
        raise SystemExit("GROQ_API_KEY (or OPENROUTER_API_KEY) is missing.")
    return out


def _parse(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def ask_json(system: str, user: str, temperature: float = 0.7, attempts: int = 4) -> dict:
    """Return a parsed JSON object. Retries rate limits and broken JSON, then
    falls over to the next provider."""
    last = ""
    for url, key, model in _providers():
        for attempt in range(1, attempts + 1):
            try:
                r = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system + "\nReturn valid JSON only."},
                            {"role": "user", "content": user},
                        ],
                    },
                    timeout=240,
                )
                if r.status_code in (429, 500, 502, 503):
                    last = f"HTTP {r.status_code}"
                    time.sleep(15 * attempt)
                    continue
                if not r.ok:
                    last = f"HTTP {r.status_code}: {r.text[:300]}"
                    break
                data = _parse(r.json()["choices"][0]["message"]["content"])
                if isinstance(data, dict):
                    return data
                last = "response was not a JSON object"
            except (json.JSONDecodeError, KeyError, IndexError, requests.RequestException) as e:
                last = str(e)[:300]
                time.sleep(5 * attempt)
        print(f"LLM provider failed ({url}): {last}", flush=True)
    raise SystemExit(f"All LLM providers failed: {last}")
