import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_TOPIC = "Black Pepper"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return value.strip("-") or "video"


def gemini(prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY secret is missing.")
    response = requests.post(
        API_URL.format(model=MODEL),
        params={"key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.8,
                "responseMimeType": "application/json",
            },
        },
        timeout=180,
    )
    if not response.ok:
        raise SystemExit(
            f"Gemini request failed: HTTP {response.status_code}: {response.text[:800]}"
        )
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit(f"Unexpected Gemini response: {json.dumps(data)[:1000]}") from exc


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Gemini returned invalid JSON: {text[:1200]}") from exc


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


def validate(package: dict) -> None:
    required = {"scorecard", "meta", "scenes"}
    missing = required - package.keys()
    if missing:
        raise SystemExit(f"Missing package sections: {sorted(missing)}")
    scenes = package["scenes"]
    if not isinstance(scenes, list) or len(scenes) < 10:
        raise SystemExit("Gemini returned too few scenes.")
    meta = package["meta"]
    for key in ("title", "description", "thumbnail_text", "hook"):
        if not str(meta.get(key, "")).strip():
            raise SystemExit(f"Missing meta field: {key}")


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
    package = parse_json(gemini(build_prompt(topic, market)))
    validate(package)
    project_dir = write_outputs(package, topic)
    score = package["scorecard"]
    print(f"SHP Engine v2 complete: {project_dir}")
    print(f"Decision: {score.get('decision')} | Total score: {score.get('total')}")
    print(f"Title: {package['meta']['title']}")


if __name__ == "__main__":
    main()
