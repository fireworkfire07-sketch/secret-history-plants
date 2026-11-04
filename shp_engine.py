import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_TOPIC = "Black Pepper"
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
API_URL = "https://api.groq.com/openai/v1/chat/completions"


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return value.strip("-") or "video"


def groq(prompt: str, attempts: int = 3) -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise SystemExit("GROQ_API_KEY secret is missing.")
    for attempt in range(1, attempts + 1):
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "temperature": 0.8,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "Follow the instructions exactly and return valid JSON only, matching the requested schema.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=180,
        )
        if response.ok:
            break
        if response.status_code in (429, 503) and attempt < attempts:
            print(f"Groq {response.status_code}, retrying ({attempt}/{attempts})...", flush=True)
            time.sleep(20 * attempt)
            continue
        raise SystemExit(
            f"Groq request failed: HTTP {response.status_code}: {response.text[:800]}"
        )
    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit(f"Unexpected Groq response: {json.dumps(data)[:1000]}") from exc


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Groq returned invalid JSON: {text[:1200]}") from exc


def build_prompt(topic: str, market: str) -> str:
    return f"""
You are SHP Engine v2 for the English YouTube channel "The Secret History of Plants".

Create one evidence-aware, cinematic documentary package about: {topic}
Target market: {market}

Return valid JSON only with this exact top-level structure:
{{
  "scorecard": {{
    "topic": "string",
    "market": "string",
    "viral_potential": 0,
    "curiosity": 0,
    "competition_opportunity": 0,
    "visual_strength": 0,
    "story_strength": 0,
    "search_intent": 0,
    "total": 0,
    "decision": "PRODUCE or REWORK",
    "reason": "short explanation"
  }},
  "meta": {{
    "title": "under 100 characters",
    "description": "YouTube description",
    "hashtags": ["#example"],
    "thumbnail_text": "maximum 4 words",
    "hook": "first 20 seconds"
  }},
  "scenes": [
    {{
      "scene": 1,
      "narration": "1 to 3 short sentences",
      "visual_prompt": "specific cinematic 16:9 visual prompt"
    }}
  ]
}}

Rules:
- English only.
- Aim for 6 to 8 minutes of narration.
- Use 35 to 55 micro-scenes.
- Open with the strongest verified mystery, danger, conflict, money, medicine, empire,
  ritual, survival, or historical consequence connected to the plant.
- Do not invent quotes, dates, scientific claims, or historical events.
- When a claim is uncertain, phrase it cautiously.
- No generic intro, no filler, no repeated facts.
- Every scene must create a new question, reveal, reversal, or consequence.
- Put the biggest satisfying reveal near the end.
- Score each category from 0 to 100 and set total to the rounded average.
"""


MIN_SCENES = 10
MAX_GENERATION_ATTEMPTS = 3


def validate(package: dict) -> None:
    required = {"scorecard", "meta", "scenes"}
    missing = required - package.keys()
    if missing:
        raise SystemExit(f"Missing package sections: {sorted(missing)}")
    scenes = package["scenes"]
    if not isinstance(scenes, list) or len(scenes) < MIN_SCENES:
        count = len(scenes) if isinstance(scenes, list) else 0
        raise SystemExit(f"Groq returned too few scenes ({count}).")
    meta = package["meta"]
    for key in ("title", "description", "thumbnail_text", "hook"):
        if not str(meta.get(key, "")).strip():
            raise SystemExit(f"Missing meta field: {key}")


def generate_package(topic: str, market: str) -> dict:
    # Groq occasionally returns valid JSON with fewer than MIN_SCENES scenes
    # despite the prompt asking for 35-55 (observed twice in production runs
    # on 2026-07-30, same topic, no HTTP error — a sampling issue, not a
    # request failure). groq() already retries on HTTP 429/503; this extends
    # the same retry philosophy to a short-but-valid response, instead of
    # failing the whole pipeline on the first undersized attempt.
    package = {}
    scene_count = 0
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        package = parse_json(groq(build_prompt(topic, market)))
        scenes = package.get("scenes")
        scene_count = len(scenes) if isinstance(scenes, list) else 0
        if scene_count >= MIN_SCENES:
            return package
        print(
            f"Groq returned only {scene_count} scenes (attempt {attempt}/{MAX_GENERATION_ATTEMPTS}), retrying...",
            flush=True,
        )
    raise SystemExit(
        f"Groq returned too few scenes after {MAX_GENERATION_ATTEMPTS} attempts (last: {scene_count})."
    )


def write_outputs(package: dict, topic: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    project_dir = Path("projects") / f"{timestamp}-{slugify(topic)}"
    project_dir.mkdir(parents=True, exist_ok=True)
    scenes = package["scenes"]
    script = "\n\n".join(str(scene["narration"]).strip() for scene in scenes)
    meta = package["meta"]
    meta_txt = "\n".join([
        str(meta["title"]).strip(),
        "",
        str(meta["description"]).strip(),
        "",
        " ".join(meta.get("hashtags", [])),
        "",
        f"THUMBNAIL: {meta['thumbnail_text']}",
        f"HOOK: {meta['hook']}",
    ]).strip()
    files = {
        "script.txt": script,
        "meta.txt": meta_txt,
        "scenes.json": json.dumps(scenes, ensure_ascii=False, indent=2),
        "scorecard.json": json.dumps(package["scorecard"], ensure_ascii=False, indent=2),
        "package.json": json.dumps(package, ensure_ascii=False, indent=2),
    }
    for name, content in files.items():
        Path(name).write_text(content, encoding="utf-8")
        (project_dir / name).write_text(content, encoding="utf-8")
    return project_dir


def main() -> None:
    topic = os.environ.get("VIDEO_TOPIC") or (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TOPIC)
    market = os.environ.get("VIDEO_MARKET", "English-speaking global audience")
    package = generate_package(topic, market)
    validate(package)
    project_dir = write_outputs(package, topic)
    score = package["scorecard"]
    print(f"SHP Engine v2 complete: {project_dir}")
    print(f"Decision: {score.get('decision')} | Total score: {score.get('total')}")
    print(f"Title: {package['meta']['title']}")


if __name__ == "__main__":
    main()
