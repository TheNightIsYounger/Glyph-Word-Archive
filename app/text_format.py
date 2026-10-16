"""Shared formatting for vocabulary headings and dictionary definitions."""
import re
import sqlite3
from functools import lru_cache
from contextlib import closing

from paths import DICTIONARY_DIR


def word_key(value):
    return " ".join(value.split()).casefold()


@lru_cache(maxsize=4096)
def standard_word(value):
    key = word_key(value)
    dictionary = DICTIONARY_DIR / "dictionary.db"
    if dictionary.exists():
        try:
            with closing(sqlite3.connect(dictionary.as_uri() + "?mode=ro", uri=True)) as db:
                rows = db.execute(
                    "SELECT DISTINCT word FROM entries WHERE word=? COLLATE NOCASE ORDER BY word",
                    (key,),
                ).fetchall()
            spellings = [row[0] for row in rows]
            if key in spellings:
                return key
            if len(spellings) == 1:
                return spellings[0]
        except sqlite3.Error:
            pass
    # English's first-person pronoun remains capitalized inside phrases too.
    return re.sub(r"\bi\b", "I", key)


def sentence_start(value):
    """Capitalize the first letter without lowercasing acronyms or proper names."""
    for index, character in enumerate(value):
        if character.isalpha():
            return value[:index] + character.upper() + value[index + 1:]
    return value
