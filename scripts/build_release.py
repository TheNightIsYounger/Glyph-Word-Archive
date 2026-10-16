#!/usr/bin/env python3
"""Build privacy-safe source/full archives using an explicit file allowlist."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
FILES = ("README.md", "APPIMAGE.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "requirements.txt", "install.py", ".gitignore")
FOLDERS = {"app": ("*.py",), "assets": ("glyph.*",), "bin": ("*",), "licenses": ("*.txt",), "scripts": ("*.py", "*.sh", "AppRun", "*.json"), "tests": ("*.py",)}
DATABASES = {"dictionary.db": {"entries"}, "wordnet.db": {"members", "definitions", "antonyms", "related"}}


def hash_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive(with_dictionaries=None, output=None):
    output = Path(output or ROOT / "dist"); output.mkdir(parents=True, exist_ok=True)
    stem = f"glyph-{VERSION}-linux" + ("-with-dictionaries" if with_dictionaries else "-source")
    destination = output / f"{stem}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="glyph-release-") as temporary:
        package = Path(temporary) / stem; package.mkdir()
        for name in FILES:
            shutil.copy2(ROOT / name, package / name)
        for folder, patterns in FOLDERS.items():
            target = package / folder; target.mkdir()
            for source in sorted({path for pattern in patterns for path in (ROOT / folder).glob(pattern)}):
                if source.is_file() and not source.is_symlink(): shutil.copy2(source, target / source.name)
        manifest = {"version": VERSION, "dictionaries": {}}
        if with_dictionaries:
            target = package / "dictionaries"; target.mkdir()
            for name, required in DATABASES.items():
                source = Path(with_dictionaries).resolve() / name
                with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
                    tables = {row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not required.issubset(tables) or tables & {"words", "encounters", "reviews", "settings", "cookies"}:
                        raise ValueError(f"拒绝打包非词典数据库：{name}")
                    with closing(sqlite3.connect(target / name)) as clean:
                        original.backup(clean)
                        clean.execute("PRAGMA journal_mode=DELETE")
                        if clean.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError(name)
                manifest["dictionaries"][name] = {"sha256": hash_file(target / name), "source": "ECDICT" if name == "dictionary.db" else "Open English WordNet 2025", "format": "Glyph SQLite conversion"}
            (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        def public_metadata(member):
            member.uid = member.gid = 0; member.uname = member.gname = "root"
            return member
        with tarfile.open(destination, "w:gz") as tar:
            tar.add(package, arcname=stem, filter=public_metadata)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary-dir", type=Path, help="只读取两个词典数据库，不会读取个人词库")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = archive(args.dictionary_dir, args.output)
    print(f"{path.name}  {path.stat().st_size} bytes\nSHA256 {hash_file(path)}")
