import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from paths import DATA_DIR, DICTIONARY_DIR, ensure_directories
from text_format import standard_word, word_key

DB_PATH = DATA_DIR / "glyph.db"
DICT_PATH = DICTIONARY_DIR / "dictionary.db"
WORDNET_PATH = DICTIONARY_DIR / "wordnet.db"


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try: return super().__exit__(*args)
        finally: self.close()


def connect(path=DB_PATH):
    db = sqlite3.connect(path, timeout=10, factory=Connection) if path == DB_PATH else sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if path == DB_PATH: db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize():
    ensure_directories()
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY,
            display TEXT NOT NULL,
            normalized TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            encounter_count INTEGER NOT NULL DEFAULT 1,
            selected_sense TEXT,
            suspended INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS word_collections (
            word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            PRIMARY KEY(word_id, collection_id)
        );
        CREATE TABLE IF NOT EXISTS encounters (
            id INTEGER PRIMARY KEY,
            word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            captured_text TEXT NOT NULL,
            source_app TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY,
            word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            related_word TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            hidden INTEGER NOT NULL DEFAULT 0,
            UNIQUE(word_id, related_word, relation_type)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            sense_key TEXT NOT NULL DEFAULT '',
            rating INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL,
            due_at TEXT,
            stability REAL NOT NULL DEFAULT 0,
            difficulty REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO settings(key,value) VALUES
          ('dictionary_mode','local'),('current_collection',''),('list_width','220');
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(words)")}
        if "display_custom" not in columns:
            db.execute("ALTER TABLE words ADD COLUMN display_custom INTEGER NOT NULL DEFAULT 0")
    with connect() as db:
        if get_setting("word_display_format_v1", "", db) != "1":
            rows = db.execute("SELECT id,display FROM words WHERE display_custom=0").fetchall()
            if rows:
                backup_path = DB_PATH.with_name("glyph.before-word-format.db")
                if not backup_path.exists():
                    with closing(sqlite3.connect(backup_path)) as backup:
                        db.backup(backup)
            db.executemany("UPDATE words SET display=? WHERE id=?",
                           [(standard_word(row["display"]), row["id"]) for row in rows])
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('word_display_format_v1','1')")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def capture(display, normalized, source_app=""):
    original = display
    normalized = word_key(display)
    display = standard_word(display)
    stamp = now()
    with connect() as db:
        row = db.execute("SELECT id FROM words WHERE normalized=?", (normalized,)).fetchone()
        if row:
            word_id = row["id"]
            db.execute("UPDATE words SET encounter_count=encounter_count+1,updated_at=? WHERE id=?", (stamp, word_id))
        else:
            cur = db.execute("INSERT INTO words(display,normalized,created_at,updated_at) VALUES(?,?,?,?)", (display, normalized, stamp, stamp))
            word_id = cur.lastrowid
        db.execute("INSERT INTO encounters(word_id,captured_text,source_app,created_at) VALUES(?,?,?,?)", (word_id, original, source_app, stamp))
        current = get_setting("current_collection", "", db)
        if current:
            collection = db.execute("SELECT id FROM collections WHERE name=?", (current,)).fetchone()
            if collection:
                db.execute("INSERT OR IGNORE INTO word_collections VALUES(?,?)", (word_id, collection["id"]))
        count = db.execute("SELECT encounter_count FROM words WHERE id=?", (word_id,)).fetchone()[0]
    return count


def list_words(query="", collection_id=None, due_only=False):
    with connect() as db:
        clauses, values = [], []
        if query:
            clauses.append("w.normalized LIKE ?"); values.append(f"%{query.lower()}%")
        if collection_id is not None:
            clauses.append("EXISTS (SELECT 1 FROM word_collections wc WHERE wc.word_id=w.id AND wc.collection_id=?)")
            values.append(collection_id)
        if due_only:
            clauses.append("(r.id IS NULL OR r.due_at<=?)"); values.append(now())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return db.execute(f"""SELECT w.* FROM words w
          LEFT JOIN reviews r ON r.id=(SELECT id FROM reviews WHERE word_id=w.id AND sense_key='' ORDER BY id DESC LIMIT 1)
          {where} ORDER BY w.updated_at DESC""", values).fetchall()


def adjust_count(word_id, delta):
    with connect() as db:
        db.execute("UPDATE words SET encounter_count=max(1,encounter_count+?),updated_at=? WHERE id=?", (delta, now(), word_id))


def rename_word(word_id, display, normalized):
    display = " ".join(display.split())
    normalized = word_key(display)
    with connect() as db:
        source = db.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
        target = db.execute("SELECT * FROM words WHERE normalized=? AND id<>?", (normalized, word_id)).fetchone()
        if target:
            db.execute("UPDATE words SET encounter_count=encounter_count+?,updated_at=? WHERE id=?", (source["encounter_count"], now(), target["id"]))
            db.execute("UPDATE encounters SET word_id=? WHERE word_id=?", (target["id"], word_id))
            db.execute("INSERT OR IGNORE INTO word_collections SELECT ?,collection_id FROM word_collections WHERE word_id=?", (target["id"], word_id))
            db.execute("DELETE FROM words WHERE id=?", (word_id,))
            return target["id"]
        db.execute("UPDATE words SET display=?,normalized=?,display_custom=1,updated_at=? WHERE id=?", (display, normalized, now(), word_id))
        return word_id


def delete_word(word_id):
    with connect() as db:
        db.execute("DELETE FROM words WHERE id=?", (word_id,))


def add_collection(name):
    clean = " ".join(name.split()).strip()
    if not clean:
        return None
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO collections(name,created_at) VALUES(?,?)", (clean, now()))
        return db.execute("SELECT id FROM collections WHERE name=?", (clean,)).fetchone()[0]


def list_collections():
    with connect() as db:
        return db.execute("SELECT c.*,COUNT(wc.word_id) AS total FROM collections c LEFT JOIN word_collections wc ON wc.collection_id=c.id GROUP BY c.id ORDER BY c.created_at").fetchall()


def add_word_to_collection(word_id, collection_id):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO word_collections(word_id,collection_id) VALUES(?,?)", (word_id, collection_id))


def collection_memberships():
    with connect() as db:
        return [(row[0], row[1]) for row in db.execute("SELECT word_id,collection_id FROM word_collections")]


def assign_words_to_collection(word_ids, collection_id):
    """Add a batch without changing encounter/review state; zero means ungrouped."""
    ids = sorted(set(int(value) for value in word_ids))
    with connect() as db:
        if collection_id == 0:
            db.executemany("DELETE FROM word_collections WHERE word_id=?", [(value,) for value in ids])
        else:
            db.executemany("INSERT OR IGNORE INTO word_collections(word_id,collection_id) VALUES(?,?)",
                           [(value, collection_id) for value in ids])


def word_collection_ids(word_id):
    with connect() as db:
        return {row[0] for row in db.execute("SELECT collection_id FROM word_collections WHERE word_id=?", (word_id,))}


def set_word_collections(word_id, collection_ids):
    with connect() as db:
        db.execute("DELETE FROM word_collections WHERE word_id=?", (word_id,))
        db.executemany("INSERT INTO word_collections(word_id,collection_id) VALUES(?,?)", ((word_id, value) for value in collection_ids))


def review_word(word_id, rating, sense_key=""):
    with connect() as db:
        previous = db.execute(
            "SELECT stability,difficulty FROM reviews WHERE word_id=? AND sense_key=? ORDER BY id DESC LIMIT 1",
            (word_id, sense_key),
        ).fetchone()
        stability = previous["stability"] if previous else 1.0
        difficulty = previous["difficulty"] if previous else 5.0
        if rating == 1:
            stability = max(0.5, stability * 0.35); difficulty = min(10, difficulty + 0.8)
        elif rating == 2:
            stability = max(1.0, stability * 1.45); difficulty = min(10, difficulty + 0.1)
        else:
            stability = max(2.0, stability * 2.35 + 1); difficulty = max(1, difficulty - 0.5)
        stamp = datetime.now(timezone.utc)
        days = max(1, round(stability))
        due = (stamp + timedelta(days=days)).isoformat(timespec="seconds")
        db.execute("INSERT INTO reviews(word_id,sense_key,rating,reviewed_at,due_at,stability,difficulty) VALUES(?,?,?,?,?,?,?)", (word_id, sense_key, rating, stamp.isoformat(timespec="seconds"), due, stability, difficulty))
        return days


def review_state(word_id, sense_key=""):
    with connect() as db:
        return db.execute(
            "SELECT * FROM reviews WHERE word_id=? AND sense_key=? ORDER BY id DESC LIMIT 1",
            (word_id, sense_key),
        ).fetchone()


def related_words(word, limit=18):
    result = {"synonym": [], "antonym": [], "family": []}
    if not WORDNET_PATH.exists(): return result
    with connect(WORDNET_PATH) as db:
        synonyms = db.execute("""SELECT DISTINCT b.word FROM members a JOIN members b ON b.synset=a.synset
          WHERE a.word=? COLLATE NOCASE AND b.word<>? COLLATE NOCASE LIMIT ?""", (word, word, limit)).fetchall()
        antonyms = db.execute("SELECT DISTINCT related FROM antonyms WHERE word=? COLLATE NOCASE LIMIT ?", (word, limit)).fetchall()
        family = db.execute("SELECT DISTINCT related FROM related WHERE word=? COLLATE NOCASE LIMIT ?", (word, limit)).fetchall()
        result = {"synonym": [r[0] for r in synonyms], "antonym": [r[0] for r in antonyms], "family": [r[0] for r in family]}
    prefixes = ("un", "re", "dis", "mis", "non", "over", "under")
    candidates = [word[len(prefix):] for prefix in prefixes if word.startswith(prefix) and len(word) > len(prefix) + 2]
    if candidates and DICT_PATH.exists():
        with sqlite3.connect(DICT_PATH) as db:
            for candidate in candidates:
                if db.execute("SELECT 1 FROM entries WHERE word=? COLLATE NOCASE LIMIT 1", (candidate,)).fetchone():
                    if candidate not in result["family"]: result["family"].insert(0, candidate)
    return result


def get_setting(key, default="", db=None):
    owner = db is None
    db = db or connect()
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if owner:
        db.close()
    return row[0] if row else default


def set_setting(key, value):
    with connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def lookup_dictionary(word):
    if not DICT_PATH.exists():
        return []
    db = sqlite3.connect(DICT_PATH)
    db.row_factory = sqlite3.Row
    try:
        return db.execute("SELECT * FROM entries WHERE word=? COLLATE NOCASE ORDER BY pos,sense_order", (word,)).fetchall()
    finally:
        db.close()


def lookup_wordnet(word):
    """Return consistent English definitions from the bundled WordNet snapshot."""
    if not WORDNET_PATH.exists():
        return []
    with connect(WORDNET_PATH) as db:
        try:
            return db.execute(
                "SELECT synset,word,pos,definition,examples FROM definitions "
                "WHERE word=? COLLATE NOCASE ORDER BY sort_order",
                (word,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
