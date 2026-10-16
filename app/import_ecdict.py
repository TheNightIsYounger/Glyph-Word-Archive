#!/usr/bin/env python3
import csv
import sqlite3
import sys
from pathlib import Path
from paths import DICTIONARY_DIR

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dictionaries" / "ecdict.mini.csv"
TARGET = DICTIONARY_DIR / "dictionary.db"


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(TARGET) as db, SOURCE.open(encoding="utf-8-sig", newline="") as source:
        db.executescript("""
        DROP TABLE IF EXISTS entries;
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL COLLATE NOCASE,
            pos TEXT NOT NULL DEFAULT '',
            sense_order INTEGER NOT NULL DEFAULT 1,
            definition_en TEXT NOT NULL DEFAULT '',
            definition_zh TEXT NOT NULL DEFAULT '',
            labels TEXT NOT NULL DEFAULT '',
            ipa TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL
        );
        CREATE INDEX entries_word ON entries(word COLLATE NOCASE);
        """)
        rows = []
        for item in csv.DictReader(source):
            word = (item.get("word") or "").strip()
            if not word:
                continue
            phonetic = (item.get("phonetic") or "").strip()
            definition = (item.get("definition") or "").replace("\\n", "\n").strip()
            translation = (item.get("translation") or "").replace("\\n", "\n").strip()
            pos = ""
            first = definition.splitlines()[0] if definition else ""
            if "." in first and len(first.split(".", 1)[0]) <= 7:
                pos = first.split(".", 1)[0]
            rows.append((word, pos, 1, definition, translation, "", phonetic, "ECDICT"))
            if len(rows) >= 5000:
                db.executemany("INSERT INTO entries(word,pos,sense_order,definition_en,definition_zh,labels,ipa,source) VALUES(?,?,?,?,?,?,?,?)", rows)
                rows.clear()
        if rows:
            db.executemany("INSERT INTO entries(word,pos,sense_order,definition_en,definition_zh,labels,ipa,source) VALUES(?,?,?,?,?,?,?,?)", rows)
        total = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print(f"Imported {total} entries")


if __name__ == "__main__":
    main()
