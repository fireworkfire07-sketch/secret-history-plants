import io, os, re, json, time, shutil, random, asyncio, subprocess, requests, urllib.parse
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

VOICE = "en-US-AndrewNeural"
RATE = "-5%"
FPS = 25
GORSEL_STIL = (
    "photorealistic cinematic documentary still, dramatic natural lighting, rich color grading, "
    "35mm film, shallow depth of field, highly detailed, no text"
)
SHORT_MIN, SHORT_MAX = 35.0, 58.0

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


# ------------------------------------------------------------------ veri
def paragraflar():
    with open("script.txt", encoding="utf-8") as f:
        text = f.read()
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def paket():
    try:
        with open("package.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def gorsel_promptlari(sahneler, pkg):
    """scenes.json'daki visual_prompt'ları kullan; yoksa anlatımdan türet."""
    sc = pkg.get("scenes") or []
    out = []
    for i, p in enumerate(sahneler):
        vp = ""
        if i < len(sc) and isinstance(sc[i], dict):
            vp = str(sc[i].get("visual_prompt", "")).strip()
        if not vp:
            vp = re.sub(r"[^a-zA-Z0-9 ]", "", p)[:150]
        out.append(vp[:300])
    return out


# ------------------------------------------------------------------ ses / görsel
async def _seslendir(text, out):
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(out)


def seslendir(text, out, deneme=5):
    for i in range(deneme):
        try:
            asyncio.run(_seslendir(text, out))
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                return
            raise ValueError("ses dosyasi bos")
        except Exception as e:
            print(f"Ses deneme {i+1}/{deneme} hata: {e}")
            time.sleep(10 * (i + 1))
    raise SystemExit(f"Ses uretilemedi: {out}")


def pollinations(prompt, w=1280, h=720, deneme=5):
    p = urllib.parse.quote(f"{prompt}, {GORSEL_STIL}")
    for i in range(deneme):
        url = (
            f"https://image.pollinations.ai/prompt/{p}?width={w}&height={h}"
            f"&nologo=true&seed={random.randint(1, 10**7)}"
        )
        try:
            r = requests.get(url, timeout=120)
            if r.ok and len(r.content) > 10000:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            raise ValueError(f"kotu cevap: {r.status_code}, {len(r.content)} byte")
        except Exception as e:
            print(f"Gorsel deneme {i+1}/{deneme} hata: {e}")
            time.sleep(15 * (i + 1))
    return None


def gorsel_uret(prompt, out):
    img = pollinations(prompt)
    if img is None:
        return False
    img.resize((1280, 720)).save(out, "JPEG", quality=92)
    return True


def sure(dosya):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", dosya],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


# ------------------------------------------------------------------ video
def _hareket(i, kare, w, h):
    """Her sahnede farklı kamera hareketi: yakınlaş, uzaklaş, sola/sağa kaydır."""
    tip = i % 4
    merkez = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if tip == 0:
        return f"zoompan=z='min(zoom+0.0009,1.18)':d={kare}:{merkez}:s={w}x{h}:fps={FPS}"
    if tip == 1:
        return f"zoompan=z='if(eq(on,0),1.18,max(zoom-0.0009,1.0))':d={kare}:{merkez}:s={w}x{h}:fps={FPS}"
    if tip == 2:
        return (f"zoompan=z=1.15:d={kare}:x='(iw-iw/zoom)*on/{kare}':y='ih/2-(ih/zoom/2)'"
                f":s={w}x{h}:fps={FPS}")
    return (f"zoompan=z=1.15:d={kare}:x='(iw-iw/zoom)*(1-on/{kare})':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps={FPS}")


def sahne_video(img, ses, out, i=0, w=1280, h=720):
    d = sure(ses)
    kare = int(d * FPS) + FPS
    vf = f"scale={w * 5 // 4}:{h * 5 // 4}," + _hareket(i, kare, w, h)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img, "-i", ses,
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k",
         "-ar", "44100", "-shortest", "-pix_fmt", "yuv420p", out],
        check=True,
    )


def birlestir(parcalar, out, liste="liste.txt"):
    with open(liste, "w", encoding="utf-8") as f:
        for p in parcalar:
            f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", liste,
         "-c", "copy", "-movflags", "+faststart", out],
        check=True,
    )


# ------------------------------------------------------------------ yazı
def _font(boyut):
    for yol in FONT_CANDIDATES:
        if os.path.exists(yol):
            return ImageFont.truetype(yol, boyut)
    return ImageFont.load_default(size=boyut)


def _sar(cizim, metin, font, max_w):
    satirlar, cur = [], ""
    for k in metin.split():
        aday = f"{cur} {k}".strip()
        if cizim.textlength(aday, font=font) <= max_w or not cur:
            cur = aday
        else:
            satirlar.append(cur)
            cur = k
    if cur:
        satirlar.append(cur)
    return satirlar


def _sigdir(cizim, metin, max_w, max_h, bas, min_boyut=40, adim=4, aralik=1.12):
    boyut = bas
    while boyut > min_boyut:
        font = _font(boyut)
        satirlar = _sar(cizim, metin, font, max_w)
        if len(satirlar) * int(boyut * aralik) <= max_h and all(
            cizim.textlength(s, font=font) <= max_w for s in satirlar
        ):
            return font, satirlar, boyut
        boyut -= adim
    font = _font(min_boyut)
    return font, _sar(cizim, metin, font, max_w), min_boyut


# ------------------------------------------------------------------ thumbnail
def meta_satirlari():
    with open("meta.txt", encoding="utf-8") as f:
        return f.read().strip().split("\n")


def meta_alan(satirlar, anahtar):
    for s in satirlar:
        if s.strip().upper().startswith(anahtar + ":"):
            return s.split(":", 1)[1].strip()
    return ""


def thumbnail_uret(metin, prompt, out="thumbnail.jpg"):
    img = pollinations(prompt or metin)
    if img is None:
        print("Thumbnail arka plani uretilemedi, koyu zemin kullaniliyor")
        img = Image.new("RGB", (1280, 720), (14, 22, 16))
    img = img.resize((1280, 720))

    # sol yarıyı karart, sağdaki obje parlak kalsın
    maske = Image.new("L", (1280, 720), 0)
    md = ImageDraw.Draw(maske)
    for x in range(1280):
        md.line([(x, 0), (x, 720)], fill=int(max(0, 215 - x * 0.30)))
    img = Image.composite(Image.new("RGB", (1280, 720), (0, 0, 0)), img, maske)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120))

    c = ImageDraw.Draw(img)
    font, satirlar, boyut = _sigdir(c, metin.upper().strip(), 690, 560, 170, 50, 6, 1.05)
    lh = int(boyut * 1.05)
    y = (720 - len(satirlar) * lh) // 2
    renkler = [(255, 214, 0), (255, 255, 255)]
    for i, s in enumerate(satirlar):
        c.text((60, y), s, font=font, fill=renkler[i % 2],
               stroke_width=max(4, boyut // 18), stroke_fill=(0, 0, 0))
        y += lh
    img.save(out, "JPEG", quality=90, optimize=True)
    return out


# ------------------------------------------------------------------ short (9:16)
def dikey_kare(img_yolu, altyazi, ust_baslik, out):
    W, H = 1080, 1920
    src = Image.open(img_yolu).convert("RGB")
    # bulanık dolgu arka plan
    bg = src.resize((int(H * src.width / src.height), H))
    sol = (bg.width - W) // 2
    bg = bg.crop((sol, 0, sol + W, H)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    # ortada büyük görsel (merkezden kare-ye yakın kırp)
    kh = 1080
    kw = int(kh * src.width / src.height)
    on = src.resize((kw, kh))
    x0 = (kw - W) // 2
    on = on.crop((x0, 0, x0 + W, kh))
    bg.paste(on, (0, 420))
    c = ImageDraw.Draw(bg)
    # üst başlık
    if ust_baslik:
        font, satirlar, b = _sigdir(c, ust_baslik.upper(), 980, 300, 92, 44, 4)
        y = 70
        for s in satirlar:
            w = c.textlength(s, font=font)
            c.text(((W - w) / 2, y), s, font=font, fill=(255, 214, 0),
                   stroke_width=max(3, b // 16), stroke_fill=(0, 0, 0))
            y += int(b * 1.12)
    # altyazı (anlatım metni)
    font, satirlar, b = _sigdir(c, altyazi, 960, 380, 64, 34, 2)
    y = 1530
    for s in satirlar:
        w = c.textlength(s, font=font)
        c.text(((W - w) / 2, y), s, font=font, fill=(255, 255, 255),
               stroke_width=max(3, b // 14), stroke_fill=(0, 0, 0))
        y += int(b * 1.12)
    bg.save(out, "JPEG", quality=90)


def short_uret(sahneler, baslik, out="short.mp4"):
    parcalar, toplam = [], 0.0
    for i, metin in enumerate(sahneler):
        ses, img = f"s{i}.mp3", f"s{i}.jpg"
        if not (os.path.exists(ses) and os.path.exists(img)):
            break
        d = sure(ses)
        if toplam + d > SHORT_MAX:
            break
        dk, dv = f"v{i}.jpg", f"v{i}.mp4"
        dikey_kare(img, metin, baslik, dk)
        sahne_video(dk, ses, dv, i=i % 2, w=1080, h=1920)  # sadece yakınlaş/uzaklaş
        parcalar.append(dv)
        toplam += d
        if toplam >= SHORT_MIN and i >= 3:
            break
    if toplam < 15:
        print("Short icin yeterli sahne yok, atlaniyor.")
        return None
    birlestir(parcalar, out, "liste_short.txt")
    print(f"Short hazir: {out} ({toplam:.1f} sn)")
    return out


# ------------------------------------------------------------------ YouTube
GIZLI = ("THUMBNAIL:", "HOOK:", "TITLE_OPTIONS:")


def _yt():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _insert(yt, video, baslik, aciklama, etiketler=None):
    body = {
        "snippet": {
            "title": baslik[:100],
            "description": aciklama[:4900],
            "categoryId": "27",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    if etiketler:
        body["snippet"]["tags"] = etiketler[:15]
    res = yt.videos().insert(
        part="snippet,status", body=body, media_body=MediaFileUpload(video, resumable=True)
    ).execute()
    return res["id"]


def yukle(video, thumbnail=None, short=None, short_baslik=""):
    satirlar = meta_satirlari()
    baslik = satirlar[0][:100]
    aciklama = "\n".join(s for s in satirlar[1:] if not s.strip().upper().startswith(GIZLI)).strip()
    etiketler = [w.lstrip("#") for w in re.findall(r"#\w+", aciklama)]
    yt = _yt()

    video_id = _insert(yt, video, baslik, aciklama, etiketler)
    print("Yuklendi:", "https://youtu.be/" + video_id)

    if thumbnail and os.path.exists(thumbnail):
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail)).execute()
            print("Thumbnail ayarlandi.")
        except HttpError as e:
            print(f"UYARI: thumbnail ayarlanamadi (kanal dogrulanmamis olabilir, HTTP {e.status_code}): {e}")
        except Exception as e:
            print(f"UYARI: thumbnail ayarlanirken beklenmeyen hata: {e}")

    if short and os.path.exists(short):
        try:
            sb = (short_baslik or baslik)[:90] + " #shorts"
            sa = (f"Full documentary: https://youtu.be/{video_id}\n\n{baslik}\n\n"
                  + " ".join("#" + e for e in etiketler[:5]))
            sid = _insert(yt, short, sb, sa, etiketler)
            print("Short yuklendi:", "https://youtube.com/shorts/" + sid)
        except Exception as e:
            print(f"UYARI: Short yuklenemedi: {e}")

    return video_id


# ------------------------------------------------------------------ ana akış
def main():
    sahneler = paragraflar()
    if not sahneler:
        raise SystemExit("script.txt is empty")
    pkg = paket()
    meta = pkg.get("meta", {})
    promptlar = gorsel_promptlari(sahneler, pkg)

    parcalar = []
    onceki_img = None
    for i, p in enumerate(sahneler):
        ses, img, vid = f"s{i}.mp3", f"s{i}.jpg", f"s{i}.mp4"
        seslendir(p, ses)
        if not gorsel_uret(promptlar[i], img):
            if onceki_img:
                print(f"Sahne {i+1}: gorsel uretilemedi, onceki gorsel kullaniliyor")
                shutil.copy(onceki_img, img)
            else:
                raise SystemExit(f"Gorsel uretilemedi: sahne {i}")
        onceki_img = img
        sahne_video(img, ses, vid, i=i)
        parcalar.append(vid)
        print(f"Sahne {i+1}/{len(sahneler)} tamam")

    birlestir(parcalar, "final.mp4")
    print("Video hazir: final.mp4")

    ms = meta_satirlari()
    thumb_metni = meta_alan(ms, "THUMBNAIL") or " ".join(ms[0].split()[:4])
    thumb_prompt = str(meta.get("thumbnail_prompt", "")).strip() or promptlar[0]
    thumbnail_uret(thumb_metni, thumb_prompt, "thumbnail.jpg")
    print(f"Thumbnail hazir: thumbnail.jpg ('{thumb_metni}')")

    short_baslik = str(meta.get("short_title", "")).strip()
    short = None
    if os.environ.get("SKIP_SHORT", "").lower() not in {"1", "true", "yes"}:
        try:
            short = short_uret(sahneler, short_baslik or thumb_metni)
        except Exception as e:
            print(f"UYARI: Short uretilemedi: {e}")

    if os.environ.get("SKIP_YOUTUBE_UPLOAD", "").lower() in {"1", "true", "yes"}:
        print("YouTube upload skipped for test run.")
        return

    required = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing YouTube secrets: {', '.join(missing)}")
    yukle("final.mp4", "thumbnail.jpg", short, short_baslik)


if __name__ == "__main__":
    main()
