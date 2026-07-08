import os
import re
from anthropic import Anthropic

TOPIC = os.environ.get("VIDEO_TOPIC", "Black Pepper")

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

prompt = f"""
You are SHP CORE for The Secret History of Plants.

Create a cinematic English documentary package.

Topic:
{TOPIC}

Return exactly in this format:

===META===
First line: best YouTube title.
Then write YouTube description, chapters, hashtags.

===SCRIPT===
Write the full documentary script.
8-10 minutes.
Micro-scenes.
One narration beat per line.
Blank line between sections.
English only.
No brackets.
"""

msg = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=8000,
    temperature=0.7,
    messages=[{"role": "user", "content": prompt}],
)

text = msg.content[0].text

meta = re.search(r"===META===(.*?)===SCRIPT===", text, re.S)
script = re.search(r"===SCRIPT===(.*)", text, re.S)

if not meta or not script:
    raise SystemExit("Claude output format error.")

open("meta.txt", "w", encoding="utf-8").write(meta.group(1).strip())
open("script.txt", "w", encoding="utf-8").write(script.group(1).strip())

print("Generated script.txt and meta.txt")
