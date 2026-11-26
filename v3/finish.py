"""Thumbnail + optional YouTube upload for a rendered v3 video (reuses pipeline.py helpers)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline  # noqa: E402


def main() -> None:
    story = json.loads(Path("story.json").read_text(encoding="utf-8"))
    meta = story.get("meta", {})
    text = meta.get("thumbnail_text") or " ".join(meta.get("title", story["topic"]).split()[:4])
    prompt = meta.get("thumbnail_prompt") or story["topic"]
    pipeline.thumbnail_uret(text, prompt, "thumbnail.jpg")
    print(f"Thumbnail ready: '{text}'")

    if os.environ.get("UPLOAD", "false").lower() != "true":
        print("Upload skipped (review the artifact first).")
        return
    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing YouTube secrets: {', '.join(missing)}")
    pipeline.yukle("final.mp4", "thumbnail.jpg", None)


if __name__ == "__main__":
    main()
