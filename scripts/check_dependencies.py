#!/usr/bin/env python3
import importlib.util
import shutil
import subprocess


def main():
    missing = []
    for name in ("PyQt6.QtWidgets", "PyQt6.QtWebEngineWidgets"):
        try: found = importlib.util.find_spec(name) is not None
        except ModuleNotFoundError: found = False
        print(f"{'OK' if found else 'MISSING'} {name}")
        if not found: missing.append(name)
    for name in ("wl-paste", "grim", "slurp", "tesseract", "notify-send"):
        found = shutil.which(name)
        print(f"{'OK' if found else 'MISSING'} {name}")
        if not found: missing.append(name)
    if shutil.which("tesseract"):
        data = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
        if "eng" not in data.stdout.split(): missing.append("tesseract English language data")
    print("niri integration: " + ("available" if shutil.which("niri") else "not available; global shortcuts unsupported here"))
    return bool(missing)


if __name__ == "__main__": raise SystemExit(main())
