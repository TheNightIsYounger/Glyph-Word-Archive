#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture import clean_selection, notify
from database import capture, initialize
from paths import APP_ID, ASSET_DIR
from text_format import standard_word


def run(command, timeout=20):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def recognize():
    area = run(["slurp"], timeout=60)
    if area.returncode != 0 or not area.stdout.strip():
        return ""
    with tempfile.TemporaryDirectory(prefix="glyph-ocr-") as folder:
        image = str(Path(folder) / "selection.png")
        shot = run(["grim", "-g", area.stdout.strip(), image])
        if shot.returncode != 0:
            raise RuntimeError("区域截图失败")
        result = run(["tesseract", image, "stdout", "-l", "eng", "--psm", "7"])
        if result.returncode != 0:
            raise RuntimeError("OCR 识别失败")
    raw = " ".join(result.stdout.replace("|", "I").split())
    direct = clean_selection(raw)
    if direct:
        return direct
    candidates = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", raw)
    return max(candidates, key=len) if candidates else ""


def confirm_word(guess):
    dialog = QDialog()
    dialog.setWindowTitle("Glyph OCR")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("识别结果（可修改）"))
    entry = QLineEdit(guess)
    entry.selectAll()
    layout.addWidget(entry)
    button_row = QHBoxLayout()
    button_row.setSpacing(12)
    button_row.addStretch(1)
    cancel = QPushButton("取消"); save = QPushButton("收录")
    for button in (cancel, save):
        button.setIcon(QIcon())
        button.setFixedWidth(92)
    cancel.clicked.connect(dialog.reject)
    save.clicked.connect(dialog.accept)
    save.setDefault(True)
    button_row.addWidget(cancel)
    button_row.addWidget(save)
    button_row.addStretch(1)
    layout.addLayout(button_row)
    entry.returnPressed.connect(dialog.accept)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return ""
    return entry.text()


def main():
    initialize()
    app = QApplication(sys.argv)
    app.setApplicationName("Glyph OCR")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon(str(ASSET_DIR / "glyph.png")))
    try:
        guess = recognize()
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
        notify("OCR 失败", str(error))
        return 1
    if not guess:
        notify("没有识别到单词", "请只框住一个英文单词，边缘稍微留白")
        return 1
    word = clean_selection(confirm_word(standard_word(guess)))
    if not word:
        return 0
    count = capture(word, word.casefold(), "ocr")
    notify("OCR Captured", f"{word}  ×{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
