#!/usr/bin/env python3
"""Fetch the declared upstream data; no dictionary scraping or website bypass."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from paths import DICTIONARY_DIR

SOURCES = {
    "ecdict": ("https://raw.githubusercontent.com/skywind3000/ECDICT/82c9872/ecdict.csv", "ecdict.csv", "import_ecdict.py", "ECDICT commit 82c9872, MIT"),
    "wordnet": ("https://en-word.net/static/english-wordnet-2025-json.zip", "english-wordnet-2025-json.zip", "import_wordnet.py", "Open English WordNet 2025, CC BY 4.0 and Princeton WordNet License"),
}
EXPECTED = {
    "ecdict": "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf",
    "wordnet": "7d749f6e2c39e6970e4997839dcf6e42fd281f3c2fae0171d2192bae8cfa4b51",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DICTIONARY_DIR)
    parser.add_argument("--accept-licenses", action="store_true", help="确认已阅读仓库中对应词典许可与来源说明")
    args = parser.parse_args()
    if not args.accept_licenses:
        parser.error("请先阅读 licenses/ 和 THIRD_PARTY_NOTICES.md，再加 --accept-licenses")
    args.target.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with tempfile.TemporaryDirectory(prefix="glyph-dictionaries-") as temporary:
        for key, (url, filename, importer, notice) in SOURCES.items():
            source = Path(temporary) / filename
            print(f"Downloading {key} from {url}", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "Glyph/0.1.0 dictionary-setup"})
            with urllib.request.urlopen(request, timeout=60) as response, source.open("wb") as output:
                while chunk := response.read(1024 * 1024): output.write(chunk)
            with source.open("rb") as data: digest = hashlib.file_digest(data, "sha256").hexdigest()
            if digest != EXPECTED[key]:
                raise ValueError(f"{key} 下载指纹与已审核版本不同，停止导入；请核对上游变更。")
            # Import into a staging directory, then replace only a completed DB.
            staging = Path(temporary) / key; staging.mkdir()
            environment = dict(os.environ, GLYPH_DICTIONARY_DIR=str(staging))
            subprocess.run([sys.executable, str(ROOT / "app" / importer), str(source)], env=environment, check=True)
            name = "dictionary.db" if key == "ecdict" else "wordnet.db"
            import shutil
            candidate = args.target / (name + ".tmp")
            shutil.copy2(staging / name, candidate); candidate.replace(args.target / name)
            manifest[key] = {"source": url, "notice": notice, "source_sha256": digest}
    (args.target / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Dictionaries ready: {args.target}")


if __name__ == "__main__": main()
