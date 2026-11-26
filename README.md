# secret-history-plants

## Kurulum

GitHub Actions çalışması için repo **Settings → Secrets and variables → Actions** altında şu secret'lar tanımlı olmalı:

| Secret | Kullanıldığı yer | Zorunlu mu |
|---|---|---|
| `GROQ_API_KEY` | `shp_engine.py` — script + meta üretimi (ücretsiz Groq modeli) | Evet |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | `pipeline.py` — YouTube'a video ve thumbnail yükleme | Yalnızca upload açıksa |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Workflow hata bildirimi | Opsiyonel — yoksa bildirim adımı sessizce atlanır |

**Uyarı:** Google Cloud OAuth consent screen **"In production"** olmalı. "Testing" modunda refresh token 7 günde geçersiz olur ve upload sessizce başarısız olur.
## v3 Pro hattı (`.github/workflows/video_v3.yml`)

Actions → **SHP v3 Pro Video** → Run workflow (konu + dakika). İlk denemelerde upload kapalı kalsın; artifact'teki `final.mp4`'ü izleyip onaylayınca açın.

1. `v3/script_v3.py` – hikaye mimarı (tek büyük soru sona kadar açık, yanlış ipucu, 4 bölüm), bölüm bölüm yazar, izlenme eleştirmeni (puanlar + zayıf satırları yeniden yazar), paketleyici → `story.json`
2. `v3/assets.py` – kelime zamanlı seslendirme, AI + Wikimedia Commons arşiv görselleri, ses efektleri, müzik → `v3/remotion/timeline.json`, açıklamaya bölüm zaman damgaları + görsel kredileri
3. `v3/remotion` – Remotion ile kurgu: kelime kelime altyazı, sayı/tarih/yer animasyonları, bölüm kartları, köşede sona kadar duran soru rozeti, crossfade, film greni + renk ayarı, müzik ducking
4. `v3/finish.py` – thumbnail + (isteğe bağlı) YouTube yükleme

Müzik: `v3/music/` klasörüne YouTube Ses Kitaplığı'ndan parça koyun; yoksa sentetik ambiyans kullanılır.
Opsiyonel secret: `OPENROUTER_API_KEY` (Groq düşerse yedek).
