# secret-history-plants

## Ne işe yarar

"The Secret History of Plants" YouTube kanalı için faceless (yüzsüz) belgesel tarzı video üretip yayınlayan otomasyon. Konuyu ya `shp-engine` reposu yollar ya da elle girilir; script, seslendirme, görsel, thumbnail ve YouTube upload'ı bu repo tek başına yapar.

## Pipeline akışı

```
Konu (repository_dispatch new_topic'ten VEYA manuel "topic" girdisinden)
   → shp_engine.py   [Groq: llama-3.3-70b-versatile]
        script.txt, meta.txt (baslik/aciklama/hashtag/THUMBNAIL/HOOK), scenes.json uretir
   → pipeline.py
        her sahne icin:
          seslendir()   [edge-tts, en-US-AndrewNeural]      → s{i}.mp3
          gorsel_uret() [pollinations.ai, antik botanik illustrasyon] → s{i}.jpg
          sahne_video() [ffmpeg, Ken Burns zoom]            → s{i}.mp4
        birlestir()     [ffmpeg concat]                     → final.mp4
        thumbnail_metni()+thumbnail_uret() [pollinations.ai + Pillow] → thumbnail.jpg
        (upload acıksa) yukle() [YouTube Data API v3]
          → final.mp4 upload + thumbnails().set(thumbnail.jpg)
          → status.containsSyntheticMedia = true
```

Görsel/ses üretimi tamamen ücretsiz araçlarla (edge-tts, pollinations.ai) yapılır — ücretli bir API'ye geçilmez.

## Workflow'lar

| Dosya | Ne yapar | Nasıl tetiklenir |
|---|---|---|
| `video.yml` (SHP Pipeline) | Yukarıdaki tüm üretim zincirini çalıştırır | `repository_dispatch` (`new_topic`, `shp-engine`'den — upload otomatik açılır) **veya** manuel (`topic`, `upload_to_youtube` girdileriyle) |
| `claude.yml` (Claude Code) | Issue/PR yorumlarında `@claude` geçince Claude Code'u çalıştırır | `issue_comment`, `pull_request_review_comment`, `issues`, `pull_request` — video pipeline'ının parçası değil |

## Gerekli secret'lar

Değerler burada **asla** yazılmaz — sadece isim ve amaç. Repo → Settings → Secrets and variables → Actions.

| Secret | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `GROQ_API_KEY` | `shp_engine.py` — script/meta üretimi | Evet |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | `pipeline.py` — YouTube OAuth, video + thumbnail upload | Yalnızca `upload_to_youtube: true` iken |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Workflow başarısız olunca bildirim | Opsiyonel — yoksa adım sessizce atlanır |
| `ANTHROPIC_API_KEY` | `claude.yml` — Claude Code action | Yalnızca `@claude` yorumlarını kullanacaksan |

**Uyarı:** Google Cloud OAuth consent screen **"In production"** olmalı. "Testing" modunda refresh token 7 günde geçersiz olur ve upload sessizce başarısız olur.

## Manuel çalıştırma

GitHub'da **Actions** → **SHP Pipeline** → **Run workflow** → `topic` gir, gerçekten YouTube'a yüklensin istiyorsan `upload_to_youtube` kutusunu işaretle.

> **Not:** "Re-run" o an `main` branch'inde olan kodu çalıştırır, workflow'un ilk çalıştığı tarihteki kodu değil.

`upload_to_youtube: false` ile çalıştırırsan hiçbir şey YouTube'a gitmez; script+ses+görsel+thumbnail+render yine de üretilir ve Actions run'ının "Artifacts" bölümünden indirilebilir.

## Bilinen notlar / sorunlar

- **`shp_engine.py` şu an "Black Pepper" konusunda tekrarlı biçimde başarısız oluyor**: Groq'un döndürdüğü JSON'da 10'dan az sahne (`scenes`) geldiğinde üretim durur (`validate()`, `shp_engine.py`). Bugün iki ayrı kuru testte de aynı hata çıktı — konudan bağımsız, modelin bu prompt için tutarlı bir sorunu olabilir. Hata mesajını (eskiden yanlışlıkla "Gemini returned too few scenes" diyordu, artık "Groq...") bu PR'da düzelttim ama **kök nedeni çözmedim** — prompt/retry mantığına dokunmak riskli bir davranış değişikliği, bkz. PR açıklamasındaki Öneriler.
- `generate.py` artık hiçbir workflow tarafından çağrılmıyor — eski Gemini tabanlı script üretici, yerini Groq tabanlı `shp_engine.py` aldı. Ölü kod, silinmedi.
- `requirements.txt`'te hâlâ `google-generativeai` var — sadece kullanılmayan `generate.py`'nin bağımlılığı, aktif pipeline'da hiç import edilmiyor.
- Gerçek bir YouTube upload'ı veya `thumbnails().set()` çağrısı bu incelemede test edilmedi (upload her zaman kapalı test edildi).
