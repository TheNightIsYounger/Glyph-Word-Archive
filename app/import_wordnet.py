#!/usr/bin/env python3
import json
import sqlite3
import zipfile
import sys
from pathlib import Path
from paths import DICTIONARY_DIR

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dictionaries" / "english-wordnet-2025-json.zip"
TARGET = DICTIONARY_DIR / "wordnet.db"


def lemma_from_sense_id(value):
    return value.split("%", 1)[0].replace("_", " ").strip()


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(TARGET) as db, zipfile.ZipFile(SOURCE) as archive:
        db.executescript("""
        DROP TABLE IF EXISTS members;
        DROP TABLE IF EXISTS definitions;
        DROP TABLE IF EXISTS antonyms;
        DROP TABLE IF EXISTS related;
        CREATE TABLE members(synset TEXT NOT NULL, word TEXT NOT NULL COLLATE NOCASE);
        CREATE TABLE definitions(
            synset TEXT NOT NULL,
            word TEXT NOT NULL COLLATE NOCASE,
            pos TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            definition TEXT NOT NULL,
            examples TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE antonyms(word TEXT NOT NULL COLLATE NOCASE, related TEXT NOT NULL COLLATE NOCASE);
        CREATE TABLE related(word TEXT NOT NULL COLLATE NOCASE, related TEXT NOT NULL COLLATE NOCASE, kind TEXT NOT NULL);
        CREATE INDEX members_word ON members(word COLLATE NOCASE);
        CREATE INDEX members_synset ON members(synset);
        CREATE INDEX definitions_word ON definitions(word COLLATE NOCASE);
        CREATE INDEX antonyms_word ON antonyms(word COLLATE NOCASE);
        CREATE INDEX related_word ON related(word COLLATE NOCASE);
        """)
        member_rows, definition_rows, antonym_rows, related_rows = [], [], [], []
        definition_order = 0
        for name in archive.namelist():
            if not name.endswith(".json"):
                continue
            data = json.loads(archive.read(name))
            if name.startswith("entries-"):
                for word, parts in data.items():
                    for details in parts.values():
                        for sense in details.get("sense", []):
                            for target in sense.get("antonym", []):
                                related = lemma_from_sense_id(target)
                                if related and related.casefold() != word.casefold():
                                    antonym_rows.append((word, related))
                            for field in ("derivation", "pertainym", "participle", "also"):
                                for target in sense.get(field, []):
                                    related = lemma_from_sense_id(target)
                                    if related and related.casefold() != word.casefold():
                                        related_rows.append((word, related, field))
            else:
                for synset, details in data.items():
                    if not isinstance(details, dict):
                        continue
                    members = [word.replace("_", " ") for word in details.get("members", [])]
                    for word in members:
                        member_rows.append((synset, word))
                    definitions = details.get("definition", [])
                    if isinstance(definitions, str):
                        definitions = [definitions]
                    examples = details.get("example", [])
                    if isinstance(examples, str):
                        examples = [examples]
                    example_texts = []
                    for example in examples:
                        if isinstance(example, str):
                            example_texts.append(example)
                        elif isinstance(example, dict):
                            text = example.get("text") or example.get("value")
                            if text:
                                example_texts.append(str(text))
                    pos = details.get("partOfSpeech", "")
                    for definition in definitions:
                        definition_order += 1
                        for word in members:
                            definition_rows.append((
                                synset, word, pos, definition_order,
                                str(definition).strip(), "\n".join(example_texts),
                            ))
            if len(member_rows) >= 10000:
                db.executemany("INSERT INTO members VALUES(?,?)", member_rows); member_rows.clear()
            if len(definition_rows) >= 10000:
                db.executemany("INSERT INTO definitions VALUES(?,?,?,?,?,?)", definition_rows); definition_rows.clear()
            if len(antonym_rows) >= 5000:
                db.executemany("INSERT INTO antonyms VALUES(?,?)", antonym_rows); antonym_rows.clear()
            if len(related_rows) >= 5000:
                db.executemany("INSERT INTO related VALUES(?,?,?)", related_rows); related_rows.clear()
        if member_rows: db.executemany("INSERT INTO members VALUES(?,?)", member_rows)
        if definition_rows: db.executemany("INSERT INTO definitions VALUES(?,?,?,?,?,?)", definition_rows)
        if antonym_rows: db.executemany("INSERT INTO antonyms VALUES(?,?)", antonym_rows)
        if related_rows: db.executemany("INSERT INTO related VALUES(?,?,?)", related_rows)
        db.execute("DELETE FROM antonyms WHERE rowid NOT IN (SELECT min(rowid) FROM antonyms GROUP BY word,related)")
        db.execute("DELETE FROM related WHERE rowid NOT IN (SELECT min(rowid) FROM related GROUP BY word,related,kind)")
        print("members", db.execute("SELECT count(*) FROM members").fetchone()[0])
        print("definitions", db.execute("SELECT count(*) FROM definitions").fetchone()[0])
        print("antonyms", db.execute("SELECT count(*) FROM antonyms").fetchone()[0])
        print("related", db.execute("SELECT count(*) FROM related").fetchone()[0])


if __name__ == "__main__":
    main()
