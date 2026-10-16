#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from database import capture, initialize


def notify(title, body):
    subprocess.run(["notify-send", "-a", "Glyph", "-i", "glyph", title, body], check=False)


def selected_text():
    result = subprocess.run(
        ["wl-paste", "--no-newline"],
        capture_output=True, text=True, timeout=2,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def clean_selection(raw):
    text = " ".join(raw.replace("\u00ad", "").split())
    text = re.sub(r"^[^A-Za-z]+|[^A-Za-z'-]+$", "", text)
    if not text or len(text) > 80 or not re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*(?: [A-Za-z]+(?:['-][A-Za-z]+)*){0,5}", text):
        return ""
    return text


def main():
    initialize()
    raw = selected_text()
    word = clean_selection(raw)
    if not word:
        notify("没有收录", "请先 Ctrl+C 复制英文词汇，再按 Alt+E")
        return 1
    count = capture(word, word.casefold())
    notify("Captured", f"{word}  ×{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
