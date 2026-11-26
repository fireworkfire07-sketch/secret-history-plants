"""SHP v3 asset builder.

Reads story.json and produces everything the Remotion renderer needs:
  v3/remotion/public/run/  narration.wav, music.wav, sfx/*.wav, img/*.jpg
  v3/remotion/timeline.json   frame-accurate shots, captions (word timings),
                              on-screen texts, chapter cards, sfx, ducking
  meta.txt                    title / description (with chapter timestamps + credits)

Usage:  python v3/assets.py            (after v3/script_v3.py)
        ASSETS_OFFLINE=1 python v3/assets.py   (no network: placeholder images, silent TTS - for testing)
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import os
import random
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
REMOTION = ROOT / "remotion"
RUN = REMOTION / "public" / "run"
IMG = RUN / "img"
SFX = RUN / "sfx"
TMP = RUN / "tmp"

FPS = 30
VOICE = os.environ.get("TTS_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("TTS_RATE", "-4%")
OFFLINE = os.environ.get("ASSETS_OFFLINE", "").lower() in {"1", "true", "yes"}
UA = "SHP-v3/1.0 (https://github.com/fireworkfire07-sketch/secret-history-plants)"

GAP_BEAT = 0.14
GAP_REVEAL = 0.45
GAP_SECTION = 1.4           # chapter card breathes before narration resumes
CHAPTER_CARD_SEC = 2.6
OK_LICENSES = ("public domain", "pd", "cc0", "cc by", "cc-by", "no restrictions")

STYLE = ("photorealistic cinematic documentary still, dramatic natural light, rich film color grade, "
         "35mm, shallow depth of field, highly detailed, no text, no watermark")


# ---------------------------------------------------------------- helpers
def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def frames(sec: float) -> int:
    return int(round(sec * FPS))


def words_of(text: str) -> list[str]:
    return text.split()


# ---------------------------------------------------------------- TTS
async def _tts(text: str, mp3: Path) -> list[dict]:
    import edge_tts
    com = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    marks = []
    with open(mp3, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                marks.append({"t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7, "w": chunk["text"]})
    return marks


def tts(text: str, wav: Path) -> list[dict]:
    """Return word marks [{t, d, w}] relative to the clip start."""
    if OFFLINE:
        sec = max(1.2, len(text.split()) * 0.36)
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             f"sine=f=180:d={sec:.2f}", "-af", "volume=0.04", "-ar", "48000", "-ac", "1", str(wav)])
        return []
    mp3 = wav.with_suffix(".mp3")
    for attempt in range(5):
        try:
            marks = asyncio.run(_tts(text, mp3))
            if mp3.exists() and mp3.stat().st_size > 1000:
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                     "-af", "silenceremove=start_periods=1:start_threshold=-50dB,"
                            "areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse",
                     "-ar", "48000", "-ac", "1", str(wav)])
                return marks
        except Exception as e:  # network hiccups are common
            print(f"TTS retry {attempt + 1}: {e}", flush=True)
        time.sleep(6 * (attempt + 1))
    raise SystemExit(f"TTS failed for: {text[:60]}")


def word_timings(text: str, marks: list[dict], clip: float) -> list[dict]:
    """Map narration words to times. Uses edge-tts boundaries, falls back to
    length-weighted spreading."""
    ws = words_of(text)
    if marks and len(marks) >= len(ws) * 0.6:
        lead = marks[0]["t"]  # leading silence was trimmed
        out, mi = [], 0
        for w in ws:
            core = re.sub(r"\W", "", w).lower()
            # find the next mark whose text matches this word
            j = mi
            while j < len(marks) and re.sub(r"\W", "", marks[j]["w"]).lower() != core:
                j += 1
            if j < len(marks):
                m = marks[j]
                out.append({"w": w, "t": max(0.0, m["t"] - lead), "d": max(0.12, m["d"])})
                mi = j + 1
            else:
                prev = out[-1]["t"] + out[-1]["d"] if out else 0.0
                out.append({"w": w, "t": prev, "d": 0.25})
        return out
    weights = [len(w) + 2 for w in ws]
    total = sum(weights)
    t, out = 0.0, []
    for w, k in zip(ws, weights):
        d = clip * k / total
        out.append({"w": w, "t": t, "d": d})
        t += d
    return out


# ---------------------------------------------------------------- images
_last_poll = [0.0]


def pollinations(prompt: str, out: Path, seed: int) -> bool:
    if OFFLINE:
        return False
    token = os.environ.get("POLLINATIONS_TOKEN")
    gap = float(os.environ.get("POLLINATIONS_INTERVAL", "0" if token else "16"))
    q = urllib.parse.quote(f"{prompt[:380]}, {STYLE}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for attempt in range(4):
        wait = gap - (time.time() - _last_poll[0])
        if wait > 0:
            time.sleep(wait)
        _last_poll[0] = time.time()
        try:
            r = requests.get(f"https://image.pollinations.ai/prompt/{q}?width=1920&height=1080"
                             f"&nologo=true&model=flux&seed={seed + attempt}", headers=headers, timeout=180)
            if r.ok and len(r.content) > 20000:
                Image.open(io.BytesIO(r.content)).convert("RGB").save(out, "JPEG", quality=92)
                return True
            print(f"Pollinations {r.status_code}", flush=True)
        except Exception as e:
            print(f"Pollinations error: {e}", flush=True)
        time.sleep(10 * (attempt + 1))
    return False


_used_commons: set[str] = set()


def _strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def commons(query: str, out: Path) -> dict | None:
    """Best freely licensed Wikimedia Commons image for the query. Returns credit info."""
    if OFFLINE:
        return None
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 10,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920,
    }
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params=params,
                         headers={"User-Agent": UA}, timeout=40)
        pages = sorted((r.json().get("query", {}) or {}).get("pages", {}).values(),
                       key=lambda p: p.get("index", 99))
    except Exception as e:
        print(f"Commons search failed ({query}): {e}", flush=True)
        return None
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip(meta.get("LicenseShortName", {}).get("value", "")).lower()
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 800 or info.get("height", 0) < 500:
            continue
        if not any(k in lic for k in OK_LICENSES) or "nc" in lic.split() or "-nd" in lic:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url or url in _used_commons:
            continue
        try:
            img = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            Image.open(io.BytesIO(img.content)).convert("RGB").save(out, "JPEG", quality=92)
        except Exception:
            continue
        _used_commons.add(url)
        return {
            "title": p.get("title", "").replace("File:", ""),
            "artist": _strip(meta.get("Artist", {}).get("value", ""))[:80] or "Unknown",
            "license": _strip(meta.get("LicenseShortName", {}).get("value", "")),
            "url": info.get("descriptionurl", ""),
            "aspect": info.get("width", 16) / max(info.get("height", 9), 1),
        }
    return None


def placeholder(text: str, out: Path, seed: int) -> None:
    rnd = random.Random(seed)
    base = (rnd.randint(20, 70), rnd.randint(30, 80), rnd.randint(20, 60))
    img = Image.new("RGB", (1920, 1080), base)
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y, r = rnd.randint(0, 1920), rnd.randint(0, 1080), rnd.randint(40, 300)
        c = tuple(min(255, v + rnd.randint(10, 90)) for v in base)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(18))
    d = ImageDraw.Draw(img)
    d.text((80, 980), text[:110], fill=(255, 255, 255))
    img.save(out, "JPEG", quality=88)


# ---------------------------------------------------------------- sound
def make_sfx() -> None:
    SFX.mkdir(parents=True, exist_ok=True)
    gen = {
        "whoosh": ["-f", "lavfi", "-i", "anoisesrc=color=pink:d=0.9:a=0.6",
                   "-af", "bandpass=f=1400:w=1800,afade=t=in:d=0.45:curve=exp,"
                          "afade=t=out:st=0.45:d=0.45:curve=exp,volume=1.6"],
        "hit": ["-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*(52*t-14*t*t))*exp(-3.2*t)'"
                                     "+0.25*random(0)*exp(-28*t):d=2.2",
                "-af", "lowpass=f=900,volume=1.8"],
        "riser": ["-f", "lavfi", "-i", "aevalsrc='0.22*sin(2*PI*(160*t+190*t*t))"
                                       "+0.06*random(0)*t/2.4':d=2.4",
                  "-af", "afade=t=in:d=2.2:curve=exp,highpass=f=120,volume=1.2"],
    }
    for name, args in gen.items():
        run(["ffmpeg", "-y", "-loglevel", "error", *args, "-ar", "48000", "-ac", "2",
             str(SFX / f"{name}.wav")])


def make_music(total: float) -> str | None:
    """Use a track from v3/music/ if present (YouTube Audio Library etc.), otherwise
    synthesize a dark cinematic ambient bed."""
    out = RUN / "music.wav"
    tracks = sorted(p for p in (ROOT / "music").glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))
    if tracks:
        src = random.choice(tracks)
        print(f"Music: {src.name}", flush=True)
        run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src),
             "-t", f"{total + 1:.2f}", "-af", f"afade=t=in:d=3,afade=t=out:st={max(total - 4, 0):.2f}:d=4",
             "-ar", "48000", "-ac", "2", str(out)])
        return "run/music.wav"
    print("Music: no track in v3/music/, synthesizing ambient bed", flush=True)
    expr = ("0.10*sin(2*PI*55*t)*(0.6+0.4*sin(2*PI*0.05*t))"
            "+0.07*sin(2*PI*82.4*t)*(0.6+0.4*sin(2*PI*0.037*t+1))"
            "+0.05*sin(2*PI*130.8*t)*(0.5+0.5*sin(2*PI*0.023*t+2))"
            "+0.03*sin(2*PI*196*t)*(0.5+0.5*sin(2*PI*0.031*t+3))")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':d={total + 1:.2f}:s=48000",
         "-f", "lavfi", "-i", f"anoisesrc=color=brown:d={total + 1:.2f}:a=0.05",
         "-filter_complex", "[1]lowpass=f=400[n];[0][n]amix=inputs=2:normalize=0,"
                            "aecho=0.8:0.7:400|900:0.25|0.15,"
                            f"afade=t=in:d=4,afade=t=out:st={max(total - 4, 0):.2f}:d=4",
         "-ar", "48000", "-ac", "2", str(out)])
    return "run/music.wav"


# ---------------------------------------------------------------- build
def build(story: dict) -> dict:
    if RUN.exists():
        shutil.rmtree(RUN)
    for d in (IMG, SFX, TMP):
        d.mkdir(parents=True, exist_ok=True)
    make_sfx()

    t = 0.6  # tiny pre-roll
    clips, shots, captions, texts, chapters, sfx, speech, credits = [], [], [], [], [], [], [], []
    badge_end = None
    chapter_no = 0
    beat_no = 0
    prev_img = None

    for si, sec in enumerate(story["sections"]):
        if sec.get("is_chapter"):
            chapter_no += 1
            chapters.append({"from": frames(t), "dur": frames(CHAPTER_CARD_SEC), "index": chapter_no,
                             "title": sec["name"], "question": sec.get("question", ""), "sec": t})
            sfx.append({"src": "run/sfx/whoosh.wav", "from": frames(t), "vol": 0.55})
            t += GAP_SECTION
        elif si > 0:
            t += GAP_SECTION * 0.5
        for b in sec["beats"]:
            wav = TMP / f"b{beat_no:04d}.wav"
            marks = tts(b["narration"], wav)
            clip = dur(wav)
            clips.append((wav, t))
            start = t
            speech.append([frames(start), frames(start + clip)])

            wts = word_timings(b["narration"], marks, clip)
            emph = {w.lower() for w in b.get("emphasis", [])}
            captions.append({
                "from": frames(start), "dur": frames(clip) + 3,
                "words": [{"w": x["w"], "from": frames(x["t"]), "dur": max(3, frames(x["d"])),
                           "e": re.sub(r"\W", "", x["w"]).lower() in emph} for x in wts],
            })

            if b.get("role") == "payoff" and badge_end is None:
                badge_end = frames(start)
            if b.get("sfx") in ("whoosh", "hit"):
                sfx.append({"src": f"run/sfx/{b['sfx']}.wav", "from": frames(start), "vol": 0.6})
            if b.get("sfx") == "riser":
                sfx.append({"src": "run/sfx/riser.wav", "from": max(0, frames(start + clip - 2.4)), "vol": 0.5})
            if b.get("text"):
                texts.append({"from": frames(start + 0.15), "dur": max(frames(2.4), frames(clip)),
                              **b["text"]})

            # shots: split the beat between its shots
            n = len(b["shots"])
            gap = GAP_REVEAL if b.get("role") in ("reveal", "payoff") or b.get("sfx") == "hit" else GAP_BEAT
            span = clip + gap
            for k, sh in enumerate(b["shots"]):
                img = IMG / f"s{len(shots):04d}.jpg"
                seed = int(hashlib.md5(f"{story['topic']}{beat_no}{k}".encode()).hexdigest()[:7], 16)
                fit, credit = "cover", None
                if sh["type"] == "archival":
                    credit = commons(sh["query"], img)
                    if credit:
                        credits.append(credit)
                        a = credit["aspect"]
                        fit = "cover" if 1.55 <= a <= 1.95 else "contain"
                ok = bool(credit) or pollinations(sh.get("prompt") or sh.get("query") or b["narration"], img, seed)
                if not ok:
                    if prev_img and not OFFLINE:
                        shutil.copy(prev_img, img)
                    else:
                        placeholder(f"{sh['type']}: {sh.get('prompt') or sh.get('query')}", img, seed)
                prev_img = img
                shots.append({"src": f"run/img/{img.name}", "from": frames(start + span * k / n),
                              "fit": fit, "kind": sh["type"], "seed": seed % 1000})
            t += span
            beat_no += 1
            print(f"beat {beat_no} ok ({t:.1f}s)", flush=True)

    total = t + 2.5
    # close shot durations
    for i, s in enumerate(shots):
        nxt = shots[i + 1]["from"] if i + 1 < len(shots) else frames(total)
        s["dur"] = max(1, nxt - s["from"])

    # narration track: silence base + every clip at its offset
    narr = RUN / "narration.wav"
    inputs, filt = ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={total:.2f}"], []
    for i, (wav, start) in enumerate(clips):
        inputs += ["-i", str(wav)]
        ms = int(start * 1000)
        filt.append(f"[{i + 1}]adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(clips)))
    filt.append(f"[0]{mix}amix=inputs={len(clips) + 1}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    script = TMP / "narr_filter.txt"
    script.write_text(";".join(filt), encoding="utf-8")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex_script", str(script),
         "-map", "[out]", "-ar", "48000", "-ac", "2", str(narr)])
    music = make_music(total)
    shutil.rmtree(TMP, ignore_errors=True)

    timeline = {
        "fps": FPS, "width": 1920, "height": 1080, "durationInFrames": frames(total),
        "title": story["meta"].get("title", story["topic"]),
        "badge": story["badge"], "badgeEnd": badge_end or frames(total - 40),
        "narration": "run/narration.wav", "music": music,
        "speech": speech, "shots": shots, "captions": captions, "texts": texts,
        "chapters": [{k: v for k, v in c.items() if k != "sec"} for c in chapters], "sfx": sfx,
    }
    (REMOTION / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
    write_meta(story, chapters, credits)
    print(f"timeline.json: {len(shots)} shots, {len(captions)} caption beats, {total / 60:.1f} min", flush=True)
    return timeline


def ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def write_meta(story: dict, chapters: list[dict], credits: list[dict]) -> None:
    m = story["meta"]
    lines = [m.get("title", story["topic"])[:100], "", m.get("description_intro", ""), "",
             m.get("description_body", ""), "", "Chapters:", "0:00 Intro"]
    lines += [f"{ts(c['sec'])} {c['title']}" for c in chapters]
    lines += ["", "Subscribe for the next secret history."]
    if credits:
        lines += ["", "Archival images (Wikimedia Commons):"]
        seen = set()
        for c in credits:
            if c["url"] in seen:
                continue
            seen.add(c["url"])
            lines.append(f"- {c['title']} - {c['artist']} ({c['license']}) {c['url']}")
    tags = [str(t).replace(" ", "") for t in m.get("tags", [])][:8]
    lines += ["", " ".join("#" + t.lstrip("#") for t in tags),
              "", f"THUMBNAIL: {m.get('thumbnail_text', '')}",
              f"TITLE_OPTIONS: {' | '.join(m.get('title_options', []))}",
              f"HOOK: {story['architecture'].get('cold_open_fact', '')}"]
    Path("meta.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> None:
    story = json.loads(Path(os.environ.get("STORY_IN", "story.json")).read_text(encoding="utf-8"))
    build(story)


if __name__ == "__main__":
    main()
