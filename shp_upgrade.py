#!/usr/bin/env python3
"""
shp_upgrade.py — Yayındaki YouTube videolarının paketini (başlık, açıklama, thumbnail) toplu yükseltir.

Akış:
  1) Kanalın tüm videolarını çeker (başlık, açıklama, izlenme, süre)
  2) Her video için Groq ile 3 viral başlık + açıklama kancası + thumbnail metni + görsel promptu üretir
  3) Pollinations ile 1280x720 görsel üretir, üstüne büyük kontrastlı metin basar
  4) DRY-RUN (varsayılan): sadece rapor + thumbnail'leri klasöre yazar, kanala dokunmaz
     --apply : orijinalleri yedekler, sonra YouTube'u günceller
     --rollback : yedekten eski başlık/açıklamaları geri yükler

Kullanım:
  python shp_upgrade.py --auth                 # (bir kere) yeni refresh token al
  python shp_upgrade.py                        # dry-run, rapor: out/plan.json + out/thumbs/
  python shp_upgrade.py --apply                # gerçekten güncelle
  python shp_upgrade.py --apply --only VIDEO_ID1,VIDEO_ID2
  python shp_upgrade.py --apply --max-views 500   # sadece 500'den az izlenenleri
  python shp_upgrade.py --rollback

Ortam değişkenleri (önek --prefix ile değişir, varsayılan YT_):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
  GROQ_API_KEY   (yoksa OPENROUTER_API_KEY kullanılır)
"""

import argparse
import io
import json
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- ayarlar
CHANNEL_CONTEXT = (
    "The Secret History of Plants: cinematic English documentaries about the forgotten "
    "history of plants, fungi, flowers and spices — their role in empires, wars, medicine, "
    "poison, money and myth."
)
SCOPES = ["https://www.googleapis.com/auth/youtube"]  # update + thumbnail için gerekli
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"
OUT = Path("out")
THUMBS = OUT / "thumbs"
BACKUP = OUT / "backup.json"
PLAN = OUT / "plan.json"
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
]


# ---------------------------------------------------------------- yardımcılar
def env(prefix, name):
    v = os.getenv(f"{prefix}{name}")
    if not v:
        sys.exit(f"[HATA] Ortam değişkeni eksik: {prefix}{name}")
    return v


def iso_duration_to_sec(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def clean_title(t):
    t = re.sub(r"[<>]", "", t).strip().strip('"').strip()
    return t[:100]


# ---------------------------------------------------------------- YouTube
def get_youtube(prefix):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=env(prefix, "REFRESH_TOKEN"),
        client_id=env(prefix, "CLIENT_ID"),
        client_secret=env(prefix, "CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def do_auth(prefix):
    """Yerelde tarayıcı açıp youtube scope'lu yeni refresh token üretir."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    cfg = {
        "installed": {
            "client_id": env(prefix, "CLIENT_ID"),
            "client_secret": env(prefix, "CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    print("\nYeni refresh token (GitHub secret olarak kaydet):\n")
    print(f"{prefix}REFRESH_TOKEN={creds.refresh_token}\n")


def list_videos(yt):
    ch = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
    if not ch.get("items"):
        sys.exit("[HATA] Bu token'a bağlı kanal bulunamadı.")
    print(f"Kanal: {ch['items'][0]['snippet']['title']}")
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, token = [], None
    while True:
        r = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token
        ).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break

    videos = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(
            part="snippet,statistics,contentDetails,status", id=",".join(ids[i : i + 50])
        ).execute()
        for v in r["items"]:
            videos.append(
                {
                    "id": v["id"],
                    "snippet": v["snippet"],
                    "views": int(v["statistics"].get("viewCount", 0)),
                    "duration": iso_duration_to_sec(v["contentDetails"]["duration"]),
                    "privacy": v["status"]["privacyStatus"],
                }
            )
    return videos


def apply_update(yt, video, new_title, new_desc):
    sn = dict(video["snippet"])
    body_sn = {
        "title": new_title,
        "description": new_desc[:5000],
        "categoryId": sn.get("categoryId", "27"),
    }
    for k in ("tags", "defaultLanguage", "defaultAudioLanguage"):
        if sn.get(k):
            body_sn[k] = sn[k]
    yt.videos().update(part="snippet", body={"id": video["id"], "snippet": body_sn}).execute()


def apply_thumbnail(yt, video_id, path):
    from googleapiclient.http import MediaFileUpload

    yt.thumbnails().set(
        videoId=video_id, media_body=MediaFileUpload(str(path), mimetype="image/jpeg")
    ).execute()


# ---------------------------------------------------------------- LLM
PROMPT = """You are a YouTube packaging expert for this channel:
{ctx}

Current video:
TITLE: {title}
DESCRIPTION (first part): {desc}
VIEWS: {views}

Rewrite the packaging so it gets clicked. Rules:
- 3 DIFFERENT title angles (e.g. 1: dark secret/danger, 2: money/empire/war, 3: shocking question). Max 70 characters each.
- Curiosity gap, concrete and specific (names, numbers, places). Must stay TRUE to the video's topic — no fake claims.
- No ALL CAPS titles, no emojis, no "You won't believe".
- thumb_text: 2-4 words, uppercase, punchy, different from the title (thumbnail and title must complement, not repeat).
- image_prompt: ONE dramatic single-subject scene of the plant, cinematic, dark moody background, strong rim light, high contrast, no text, no people faces.
- description_hook: 2 short sentences that open the description, hook + promise.
- best_index: 0, 1 or 2 — the title you'd bet on.

Return ONLY valid JSON:
{{"titles": ["", "", ""], "best_index": 0, "thumb_text": "", "image_prompt": "", "description_hook": ""}}"""


def call_llm(prompt):
    providers = []
    if os.getenv("GROQ_API_KEY"):
        providers.append((GROQ_URL, os.getenv("GROQ_API_KEY"), GROQ_MODEL))
    if os.getenv("OPENROUTER_API_KEY"):
        providers.append((OPENROUTER_URL, os.getenv("OPENROUTER_API_KEY"), OPENROUTER_MODEL))
    if not providers:
        sys.exit("[HATA] GROQ_API_KEY veya OPENROUTER_API_KEY gerekli.")

    last = None
    for url, key, model in providers:
        for attempt in range(3):
            try:
                r = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.8,
                    },
                    timeout=90,
                )
                if r.status_code == 429:
                    time.sleep(10 * (attempt + 1))
                    continue
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", text, re.S)
                data = json.loads(m.group(0))
                assert len(data["titles"]) == 3
                return data
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3)
    raise RuntimeError(f"LLM başarısız: {last}")


# ---------------------------------------------------------------- thumbnail
def load_font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def fetch_image(prompt):
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt + ", cinematic, 8k, dramatic lighting, documentary still")
        + f"?width=1280&height=720&nologo=true&seed={random.randint(1, 10**6)}"
    )
    for _ in range(3):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:  # noqa: BLE001
            time.sleep(5)
    # görsel gelmezse koyu degrade arka plan
    img = Image.new("RGB", (1280, 720), (12, 20, 14))
    return img


def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_thumbnail(base, text, out_path):
    img = base.resize((1280, 720))
    # sol tarafı karart (metin okunurluğu)
    shade = Image.new("L", (1280, 720), 0)
    sd = ImageDraw.Draw(shade)
    for x in range(1280):
        sd.line([(x, 0), (x, 720)], fill=int(max(0, 200 - x * 0.28)))
    img = Image.composite(Image.new("RGB", (1280, 720), (0, 0, 0)), img, shade)
    # hafif kontrast/keskinlik
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120))

    d = ImageDraw.Draw(img)
    text = text.upper().strip()
    max_w, max_h = 700, 560
    size = 170
    while size > 50:
        font = load_font(size)
        lines = wrap(d, text, font, max_w)
        lh = int(size * 1.05)
        if len(lines) * lh <= max_h and all(d.textlength(l, font=font) <= max_w for l in lines):
            break
        size -= 6
    y = (720 - len(lines) * lh) // 2
    colors = [(255, 214, 0), (255, 255, 255)]  # sarı + beyaz satırlar
    for i, line in enumerate(lines):
        d.text(
            (60, y),
            line,
            font=font,
            fill=colors[i % 2] if len(lines) > 1 else colors[0],
            stroke_width=max(4, size // 18),
            stroke_fill=(0, 0, 0),
        )
        y += lh
    img.save(out_path, "JPEG", quality=88, optimize=True)
    # 2MB sınırı
    q = 85
    while out_path.stat().st_size > 2 * 1024 * 1024 and q > 50:
        img.save(out_path, "JPEG", quality=q, optimize=True)
        q -= 10


# ---------------------------------------------------------------- ana akış
def build_plan(videos, args):
    THUMBS.mkdir(parents=True, exist_ok=True)
    old = json.loads(PLAN.read_text()) if PLAN.exists() and not args.regen else {}
    plan = {}
    for v in videos:
        vid = v["id"]
        if vid in old:
            plan[vid] = old[vid]
            print(f"  = {vid} (önceki plan kullanıldı)")
            continue
        sn = v["snippet"]
        print(f"  > {vid} | {v['views']:>6} izlenme | {sn['title'][:60]}")
        data = call_llm(
            PROMPT.format(
                ctx=CHANNEL_CONTEXT,
                title=sn["title"],
                desc=sn.get("description", "")[:1200],
                views=v["views"],
            )
        )
        titles = [clean_title(t) for t in data["titles"]]
        best = titles[int(data.get("best_index", 0)) % 3]
        is_short = v["duration"] <= 60
        thumb_path = THUMBS / f"{vid}.jpg"
        if not is_short:
            make_thumbnail(fetch_image(data["image_prompt"]), data["thumb_text"], thumb_path)
        hook = data["description_hook"].strip()
        orig = sn.get("description", "").strip()
        new_desc = hook + "\n\n" + (orig if not orig.startswith(hook) else orig[len(hook):].strip())
        plan[vid] = {
            "old_title": sn["title"],
            "new_title": best,
            "ab_titles": titles,  # Studio > A/B Testing'e elle girilecek 3 başlık
            "thumb_text": data["thumb_text"],
            "thumb": str(thumb_path) if not is_short else None,
            "new_description": new_desc,
            "views": v["views"],
            "is_short": is_short,
        }
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
        time.sleep(2)
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="YT_", help="secret öneki (YT_, YT2_, YT3_...)")
    ap.add_argument("--auth", action="store_true", help="yeni refresh token al")
    ap.add_argument("--apply", action="store_true", help="YouTube'u gerçekten güncelle")
    ap.add_argument("--rollback", action="store_true", help="yedekten eski metadata'yı geri yükle")
    ap.add_argument("--only", default="", help="virgülle video ID listesi")
    ap.add_argument("--max-views", type=int, default=None, help="bu izlenmenin altındakiler")
    ap.add_argument("--regen", action="store_true", help="önceki planı yok say, yeniden üret")
    ap.add_argument("--no-thumbs", action="store_true", help="thumbnail yükleme")
    args = ap.parse_args()

    if args.auth:
        return do_auth(args.prefix)

    OUT.mkdir(exist_ok=True)
    yt = get_youtube(args.prefix)

    if args.rollback:
        if not BACKUP.exists():
            sys.exit("[HATA] Yedek yok: out/backup.json")
        backup = json.loads(BACKUP.read_text())
        vids = {v["id"]: v for v in list_videos(yt)}
        for vid, b in backup.items():
            if vid in vids:
                apply_update(yt, vids[vid], b["title"], b["description"])
                print(f"  ↺ {vid} geri yüklendi: {b['title'][:60]}")
        print("Not: thumbnail'ler API ile geri alınamaz, eski kapakları Studio'dan elle yükle.")
        return

    videos = [v for v in list_videos(yt) if v["privacy"] == "public"]
    if args.only:
        keep = set(args.only.split(","))
        videos = [v for v in videos if v["id"] in keep]
    if args.max_views is not None:
        videos = [v for v in videos if v["views"] < args.max_views]
    print(f"{len(videos)} video işlenecek.\n")

    plan = build_plan(videos, args)

    print("\n================ PLAN ================")
    for vid, p in plan.items():
        if vid not in {v["id"] for v in videos}:
            continue
        print(f"\n[{vid}] {p['views']} izlenme{' (Short)' if p['is_short'] else ''}")
        print(f"  ESKİ : {p['old_title']}")
        print(f"  YENİ : {p['new_title']}")
        print(f"  A/B  : {' | '.join(p['ab_titles'])}")
        print(f"  KAPAK: {p['thumb_text']}  -> {p['thumb']}")

    if not args.apply:
        print("\nDRY-RUN bitti. out/thumbs/ klasöründeki kapaklara bak, beğenirsen --apply ile çalıştır.")
        return

    # yedek (varsa üzerine yazma, ilk orijinal kalsın)
    backup = json.loads(BACKUP.read_text()) if BACKUP.exists() else {}
    for v in videos:
        backup.setdefault(
            v["id"], {"title": v["snippet"]["title"], "description": v["snippet"].get("description", "")}
        )
    BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=2))
    print(f"\nYedek alındı: {BACKUP}")

    for v in videos:
        p = plan[v["id"]]
        try:
            apply_update(yt, v, p["new_title"], p["new_description"])
            msg = "başlık+açıklama"
            if p["thumb"] and not args.no_thumbs:
                try:
                    apply_thumbnail(yt, v["id"], p["thumb"])
                    msg += "+kapak"
                except Exception as e:  # noqa: BLE001
                    msg += f" (kapak HATA: {e}. Kanal telefonla doğrulanmış mı?)"
            print(f"  ✓ {v['id']} {msg}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {v['id']} HATA: {e}")
        time.sleep(1)

    print("\nBitti. 7-14 gün sonra Studio'da gösterim TO'su ve izlenme süresini karşılaştır.")
    print("Tavsiye: en iyi 3 videoda Studio > A/B Testing'e plan.json'daki 'ab_titles' + kapakları gir.")


if __name__ == "__main__":
    main()
