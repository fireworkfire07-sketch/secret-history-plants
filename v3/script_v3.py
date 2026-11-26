"""SHP v3 script engine.

Four passes, each a separate LLM call:
  1. architect  - one big question held to the end, a false lead, 4 chapters whose
                  mini-questions hand off to each other, re-hook lines
  2. writer     - writes every section as short beats (one breath each) with shots,
                  on-screen text, sound cues and caption emphasis
  3. critic     - scores retention and rewrites weak beats (up to 2 rounds)
  4. packager   - title, thumbnail, description, tags

Output: story.json (consumed by v3/assets.py)

Usage:  VIDEO_TOPIC="Nutmeg" python v3/script_v3.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import ask_json  # noqa: E402

CHANNEL = "The Secret History of Plants"
LANG = os.environ.get("VIDEO_LANG", "English")
TARGET_MIN = float(os.environ.get("VIDEO_MINUTES", "9"))
WORDS_PER_MIN = 140
OUT = Path(os.environ.get("STORY_OUT", "story.json"))

SYSTEM = f"""You are the head writer of "{CHANNEL}", a premium YouTube documentary channel
in the style of the best history storytellers. You write in {LANG}.
Accuracy rules: never invent quotes, dates, numbers, people or events. If a claim is
debated, say so in the narration ("historians still argue..."). Prefer fewer, true,
specific facts over many vague ones."""


# ---------------------------------------------------------------- 1. architect
def architect(topic: str) -> dict:
    prompt = f"""Design the story architecture for a {TARGET_MIN:.0f}-minute documentary about: {topic}

The whole video must be built around ONE big question that the viewer only gets
answered in the final 30-60 seconds. Everything before it either deepens that question,
answers a smaller question while opening the next one, or misleads the viewer
with a believable false answer that is later overturned.

Return JSON:
{{
  "big_question": "the single question the whole video answers (specific, not vague)",
  "badge": "the big question in max 34 characters, ALL CAPS, shown on screen until the payoff",
  "payoff": "the true, specific, surprising answer revealed only at the end",
  "cold_open_fact": "the most shocking verified fact - the first sentence of the video",
  "false_lead": "the obvious answer viewers will assume, which chapter 3 or 4 overturns",
  "chapters": [
    {{
      "title": "2-4 word chapter title",
      "question": "the mini-question this chapter opens in its first beats",
      "answer": "how this chapter answers it",
      "handoff": "the closing line that answers it AND opens the next chapter's question"
    }}
  ],
  "rehooks": ["4-6 short lines that re-open curiosity mid-video, specific to this story, e.g. 'But the merchants had made one mistake.'"],
  "key_facts": [{{"fact": "verified fact used in the video", "confidence": "high|medium"}}],
  "visual_world": "1-2 sentences: the visual palette, eras and places of this film"
}}

Rules:
- Exactly 4 chapters, in an order that escalates stakes (money, power, death, discovery).
- The payoff must not be guessable from the cold open.
- No chapter may answer the big question.
- 10-16 key facts. Only facts you are confident are true."""
    return ask_json(SYSTEM, prompt, temperature=0.8)


# ---------------------------------------------------------------- 2. writer
BEAT_SCHEMA = """{
  "beats": [
    {
      "narration": "one breath: 6-16 words",
      "role": "hook | loop_open | rehook | reveal | payoff | normal",
      "shots": [
        {"type": "ai", "prompt": "cinematic still: subject, place, era, light, camera angle"},
        {"type": "archival", "query": "2-4 word Wikimedia Commons search, e.g. 'Banda Islands map'"}
      ],
      "text": {"kind": "number | date | name | place", "value": "max 4 words", "label": "max 4 words or empty"},
      "sfx": "none | whoosh | hit | riser",
      "emphasis": ["1-2 key words copied exactly from the narration"]
    }
  ]
}"""


def _section_brief(arch: dict, idx: int) -> str:
    ch = arch["chapters"]
    if idx == 0:
        return f"""SECTION: COLD OPEN (about 45 seconds, 9-12 beats)
- Beat 1 is the cold open fact, stated plainly and concretely: {arch['cold_open_fact']}
- Then 2-3 beats of escalating stakes.
- Then state the big question in the narrator's voice: {arch['big_question']}
- Then plant the false lead as the obvious answer: {arch['false_lead']}
- Last beat: a hint that the real answer is stranger, WITHOUT revealing it. Mark it role "loop_open".
- Never say "in this video", "welcome", "let's dive in" or "by the end of this video"."""
    if idx <= len(ch):
        c = ch[idx - 1]
        nxt = ch[idx]["question"] if idx < len(ch) else "the big question itself"
        return f"""SECTION: CHAPTER {idx} - {c['title']} (about {TARGET_MIN * 0.2:.1f} minutes, 22-30 beats)
- First beat opens the chapter question (role "loop_open"): {c['question']}
- Build it with specific scenes: a place, a year, a person, an object, a consequence.
- Around the middle use one re-hook (role "rehook"), pick or adapt one of: {arch['rehooks']}
- Answer the chapter question late in the chapter (role "reveal"): {c['answer']}
- Last beat is the handoff that opens the next question ({nxt}): {c['handoff']}
- Do NOT answer the big question: {arch['big_question']}"""
    return f"""SECTION: FINALE (about 1 minute, 12-16 beats)
- Return to the big question explicitly: {arch['big_question']}
- Overturn the false lead: {arch['false_lead']}
- Use a "riser" sfx beat right before the answer, then reveal the payoff (role "payoff", sfx "hit"): {arch['payoff']}
- 3-5 beats of meaning: why this changes how we see the plant today.
- Final beat: one short line inviting the viewer to the channel's next secret history (no begging)."""


def write_section(topic: str, arch: dict, idx: int, previous: list[str]) -> list[dict]:
    prev = " ".join(previous[-6:]) or "(start of film)"
    prompt = f"""Documentary topic: {topic}
Big question (held to the end): {arch['big_question']}
Visual world: {arch.get('visual_world', '')}
Verified facts you may use: {json.dumps(arch.get('key_facts', []), ensure_ascii=False)}
The film so far ends with: "{prev}"

{_section_brief(arch, idx)}

Writing rules:
- Each beat is ONE breath of narration: 6-16 words, present-tense energy, concrete nouns.
- Every beat must add a new fact, image, question, reversal or consequence. No filler, no repeats.
- Vary rhythm: some 6-word punches, some 15-word lines.
- Use "shots": 1 shot per beat; 2 shots only when the beat has 13+ words.
  Use "archival" for real people, maps, manuscripts, engravings, herbarium specimens,
  old photographs and lab history; "ai" for atmosphere, reconstructions and macro shots.
  AI prompts: photorealistic cinematic documentary still, specific subject, era, light and angle,
  no text, no logos. Never two similar shots in a row.
- "text": only for a striking number, date, name or place (about every 4-6 beats), otherwise omit it.
- "sfx": "whoosh" at a scene or era jump, "riser" before a reveal, "hit" on a reveal, else "none".
- "emphasis": 1-2 words from the narration to highlight in the captions.

Return JSON exactly in this schema:
{BEAT_SCHEMA}"""
    data = ask_json(SYSTEM, prompt, temperature=0.75)
    return [b for b in (_clean_beat(b) for b in data.get("beats", [])) if b]


def _clean_beat(b) -> dict | None:
    if not isinstance(b, dict):
        return None
    text = re.sub(r"\s+", " ", str(b.get("narration", ""))).strip()
    if not text:
        return None
    shots = []
    for s in b.get("shots") or []:
        if not isinstance(s, dict):
            continue
        t = s.get("type", "ai")
        if t == "archival" and str(s.get("query", "")).strip():
            shots.append({"type": "archival", "query": str(s["query"]).strip()[:80],
                          "prompt": str(s.get("prompt", "")).strip()[:300]})
        elif str(s.get("prompt", "")).strip():
            shots.append({"type": "ai", "prompt": str(s["prompt"]).strip()[:300]})
    if not shots:
        shots = [{"type": "ai", "prompt": text[:200]}]
    beat = {
        "narration": text,
        "role": str(b.get("role", "normal")),
        "shots": shots[:2],
        "sfx": str(b.get("sfx", "none")) if b.get("sfx") in ("none", "whoosh", "hit", "riser") else "none",
        "emphasis": [w for w in (b.get("emphasis") or []) if isinstance(w, str) and w.lower() in text.lower()][:2],
    }
    tx = b.get("text")
    if isinstance(tx, dict) and str(tx.get("value", "")).strip():
        beat["text"] = {"kind": str(tx.get("kind", "name")), "value": str(tx["value"]).strip()[:40],
                        "label": str(tx.get("label", "") or "").strip()[:40]}
    return beat


# ---------------------------------------------------------------- 3. critic
def critic(arch: dict, sections: list[dict]) -> tuple[int, dict]:
    numbered = []
    n = 0
    for s in sections:
        numbered.append(f"--- {s['name']} ---")
        for b in s["beats"]:
            numbered.append(f"[{n}] ({b['role']}) {b['narration']}")
            n += 1
    prompt = f"""You are a ruthless YouTube retention editor. Read this documentary narration.
Big question that must stay open until the finale: {arch['big_question']}
Payoff: {arch['payoff']}

{chr(10).join(numbered)}

Score 0-100 each:
- hook: do beats 0-4 make leaving feel impossible?
- loop_integrity: is the big question kept open until the finale with no early leak?
- momentum: does every beat add something new (no filler, no repetition)?
- rehooks: is curiosity re-opened at least every ~60 seconds?
- clarity: can a first-time viewer follow it?
- payoff: is the ending surprising AND satisfying?

Then list up to 15 fixes for the weakest beats. A fix replaces the narration of that
beat index (6-16 words, same facts, no invented facts). Fix leaks of the payoff,
filler, clichés ("little did they know", "in this video"), and weak hooks.

Return JSON:
{{"scores": {{"hook": 0, "loop_integrity": 0, "momentum": 0, "rehooks": 0, "clarity": 0, "payoff": 0}},
 "total": 0,
 "fixes": [{{"i": 0, "narration": "new line", "why": "short reason"}}],
 "notes": "one-sentence diagnosis"}}"""
    data = ask_json("You are a precise, critical script editor.", prompt, temperature=0.3)
    flat = [b for s in sections for b in s["beats"]]
    applied = 0
    for fx in data.get("fixes", []) or []:
        try:
            i = int(fx.get("i"))
            new = re.sub(r"\s+", " ", str(fx.get("narration", ""))).strip()
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(flat) and 3 <= len(new.split()) <= 22:
            flat[i]["narration"] = new
            flat[i]["emphasis"] = [w for w in flat[i].get("emphasis", []) if w.lower() in new.lower()]
            applied += 1
    scores = data.get("scores", {}) or {}
    total = int(data.get("total") or (sum(scores.values()) / max(len(scores), 1) if scores else 0))
    print(f"Critic: total={total} applied_fixes={applied} notes={data.get('notes', '')}", flush=True)
    return total, data


# ---------------------------------------------------------------- 4. packager
def packager(topic: str, arch: dict, sections: list[dict]) -> dict:
    script = " ".join(b["narration"] for s in sections for b in s["beats"])
    prompt = f"""Package this documentary for YouTube.
Topic: {topic}
Big question: {arch['big_question']}
Chapters: {[c['title'] for c in arch['chapters']]}
Script (excerpt): {script[:3500]}

Return JSON:
{{
  "title": "best title, max 65 chars",
  "title_options": ["3 alternatives, different angles"],
  "thumbnail_text": "2-4 UPPERCASE words that add to the title, never repeat it",
  "thumbnail_prompt": "one hero subject, dark moody background, strong rim light, photorealistic, high contrast, no text, no faces",
  "description_intro": "2-3 sentence hook paragraph that opens the big question without answering it",
  "description_body": "1 paragraph naming the people, places and eras covered (search-friendly, no answer spoilers)",
  "tags": ["10-15 search tags"],
  "short_title": "max 55 chars teaser for the Short"
}}
Title rules: concrete and specific (names, numbers, empires, places), a curiosity gap,
must stay true. Never "The History of X". No ALL CAPS words, no emojis."""
    return ask_json("You are a YouTube packaging expert for documentary channels.", prompt, temperature=0.8)


# ---------------------------------------------------------------- main
def main() -> None:
    topic = os.environ.get("VIDEO_TOPIC") or (sys.argv[1] if len(sys.argv) > 1 else "Nutmeg")
    print(f"[1/4] Architect: {topic}", flush=True)
    arch = architect(topic)
    for key in ("big_question", "badge", "payoff", "cold_open_fact", "false_lead", "chapters"):
        if not arch.get(key):
            raise SystemExit(f"Architect output missing: {key}")
    arch["chapters"] = arch["chapters"][:4]

    print("[2/4] Writer", flush=True)
    names = ["Cold open"] + [c["title"] for c in arch["chapters"]] + ["Finale"]
    sections, spoken = [], []
    for idx, name in enumerate(names):
        beats = write_section(topic, arch, idx, spoken)
        if len(beats) < 5:
            beats = write_section(topic, arch, idx, spoken)
        if not beats:
            raise SystemExit(f"Writer returned no beats for section {name}")
        sections.append({"name": name, "is_chapter": 0 < idx <= len(arch["chapters"]),
                         "question": arch["chapters"][idx - 1]["question"] if 0 < idx <= len(arch["chapters"]) else "",
                         "beats": beats})
        spoken += [b["narration"] for b in beats]
        print(f"  {name}: {len(beats)} beats", flush=True)

    print("[3/4] Retention critic", flush=True)
    total, review = critic(arch, sections)
    rounds = [review]
    if total < int(os.environ.get("CRITIC_PASS", "82")):
        total, review = critic(arch, sections)
        rounds.append(review)

    print("[4/4] Packager", flush=True)
    meta = packager(topic, arch, sections)

    words = sum(len(b["narration"].split()) for s in sections for b in s["beats"])
    story = {
        "topic": topic,
        "channel": CHANNEL,
        "architecture": arch,
        "badge": arch["badge"].upper()[:40],
        "sections": sections,
        "meta": meta,
        "review": {"final_total": total, "rounds": rounds},
        "stats": {"words": words, "est_minutes": round(words / WORDS_PER_MIN, 1),
                  "beats": sum(len(s["beats"]) for s in sections)},
    }
    OUT.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"story.json ready: {story['stats']} | retention score {total} | title: {meta.get('title')}")


if __name__ == "__main__":
    main()
