"""Database schema and connection handling (SQLAlchemy Core + SQLite WAL)."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    Column, Float, ForeignKey, Index, Integer, LargeBinary, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, event, text,
)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("HANABI_DB", ROOT / "data" / "hanabi.db"))            # your account + progress
CONTENT_DB = Path(os.environ.get("HANABI_CONTENT_DB", ROOT / "data" / "content.db"))  # shipped learning content

metadata = MetaData()

# ------------------------------------------------------------------ users
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32), nullable=False, unique=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("display_name", String(64), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("xp", Integer, nullable=False, server_default="0"),
)
sessions = Table(
    "sessions", metadata,
    Column("id_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("csrf", String(64), nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("last_seen", Integer, nullable=False),
)
password_resets = Table(
    "password_resets", metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("used", Integer, nullable=False, server_default="0"),
)
settings = Table(
    "settings", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("daily_goal", Integer, nullable=False, server_default="20"),
    Column("theme", String(8), nullable=False, server_default="system"),
    Column("show_romaji", Integer, nullable=False, server_default="1"),
    Column("show_jlpt", Integer, nullable=False, server_default="1"),
    Column("mastery_accuracy", Integer, nullable=False, server_default="85"),
    Column("mastery_reps", Integer, nullable=False, server_default="4"),
    Column("mastery_interval", Integer, nullable=False, server_default="21"),
    Column("burst_minutes", Integer, nullable=False, server_default="5"),
    Column("calm_mode", Integer, nullable=False, server_default="0"),
    Column("celebrations", Integer, nullable=False, server_default="1"),
    Column("timezone", String(64), nullable=False, server_default="UTC"),
    Column("anki_autoplay", Integer, nullable=False, server_default="1"),  # play imported decks' audio automatically
    Column("palette", String(16), nullable=False, server_default="hanabi"),  # colour palette
)
# Per-item learning statistics, any track.
progress = Table(
    "progress", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("track", String(16), nullable=False),  # hiragana|katakana|hvocab|kvocab|kanji
    Column("item", String(64), nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("correct", Integer, nullable=False, server_default="0"),
    Column("mastered_at", Integer),
    Column("updated_at", Integer, nullable=False),
    UniqueConstraint("user_id", "track", "item"),
)
srs_cards = Table(
    "srs_cards", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("track", String(16), nullable=False),
    Column("item", String(64), nullable=False),
    Column("ease", Float, nullable=False, server_default="2.5"),
    Column("interval_days", Float, nullable=False, server_default="0"),
    Column("reps", Integer, nullable=False, server_default="0"),  # consecutive successes
    Column("lapses", Integer, nullable=False, server_default="0"),
    Column("total_reviews", Integer, nullable=False, server_default="0"),
    Column("total_correct", Integer, nullable=False, server_default="0"),
    Column("state", String(10), nullable=False, server_default="new"),  # new|learning|review|mastered
    Column("due_at", Integer, nullable=False),
    Column("last_review_at", Integer),
    Column("created_at", Integer, nullable=False),
    # Anki-style features (schema v4)
    Column("deck_id", Integer, ForeignKey("decks.id", ondelete="CASCADE")),  # NULL = not in a deck (kana lessons, words)
    Column("position", Integer, nullable=False, server_default="0"),          # order new cards are introduced
    Column("suspended", Integer, nullable=False, server_default="0"),
    Column("buried_until", Integer, nullable=False, server_default="0"),
    Column("introduced_at", Integer),                                         # time of the first review
    UniqueConstraint("user_id", "track", "item"),
)
Index("ix_srs_due", srs_cards.c.user_id, srs_cards.c.due_at)
Index("ix_srs_deck", srs_cards.c.deck_id, srs_cards.c.total_reviews, srs_cards.c.position)
decks = Table(
    "decks", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(80), nullable=False),
    Column("new_per_day", Integer, nullable=False, server_default="10"),
    Column("max_reviews", Integer, nullable=False, server_default="200"),
    Column("created_at", Integer, nullable=False),
    UniqueConstraint("user_id", "name"),
)
# Your own notes on any item (shown on its page and on the back of its card).
notes = Table(
    "notes", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("track", String(16), nullable=False),
    Column("item", String(64), nullable=False),
    Column("meaning", String(300), nullable=False, server_default=""),
    Column("mnemonic", Text, nullable=False, server_default=""),
    Column("notes", Text, nullable=False, server_default=""),
    Column("updated_at", Integer, nullable=False),
    UniqueConstraint("user_id", "track", "item"),
)
# Free-form cards: imported from Anki or made by hand. srs track "card", item = str(id).
custom_cards = Table(
    "custom_cards", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("front", Text, nullable=False),
    Column("back", Text, nullable=False),
    Column("extra", Text, nullable=False, server_default=""),
    Column("source", String(120), nullable=False, server_default="manual"),
    Column("created_at", Integer, nullable=False),
    # Imported from Anki (schema v5): rendered with the deck's own note type, like Anki does.
    Column("model_id", Integer, ForeignKey("anki_models.id", ondelete="SET NULL")),
    Column("fields_json", Text),   # {"Field name": "raw field HTML", ...}
    Column("ord", Integer, nullable=False, server_default="0"),  # which template (or cloze number - 1)
    Column("tags", String(500), nullable=False, server_default=""),
)
# Anki note types (card templates + styling) and media (images, fonts) that came with an imported deck.
anki_models = Table(
    "anki_models", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("deck_id", Integer, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(200), nullable=False),
    Column("kind", Integer, nullable=False, server_default="0"),  # 0 standard, 1 cloze
    Column("css", Text, nullable=False, server_default=""),
    Column("tmpls_json", Text, nullable=False),
    Column("flds_json", Text, nullable=False),
)
anki_media = Table(
    "anki_media", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("deck_id", Integer, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(400), nullable=False),
    Column("mime", String(60), nullable=False),
    Column("data", LargeBinary, nullable=False),
    UniqueConstraint("deck_id", "name"),
)
# Dictionaries you import yourself (Yomitan .zip, CSV/TSV).
user_dicts = Table(
    "user_dicts", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("title", String(120), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("entries", Integer, nullable=False, server_default="0"),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", Integer, nullable=False),
)
user_dict_entries = Table(
    "user_dict_entries", metadata,
    Column("id", Integer, primary_key=True),
    Column("dict_id", Integer, ForeignKey("user_dicts.id", ondelete="CASCADE"), nullable=False),
    Column("term", String(200), nullable=False),
    Column("reading", String(200), nullable=False, server_default=""),
    Column("meaning", Text, nullable=False),
)
Index("ix_ude_term", user_dict_entries.c.dict_id, user_dict_entries.c.term)
Index("ix_ude_reading", user_dict_entries.c.dict_id, user_dict_entries.c.reading)
reviews = Table(
    "reviews", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("card_id", Integer, ForeignKey("srs_cards.id", ondelete="CASCADE"), nullable=False),
    Column("rating", Integer, nullable=False),
    Column("interval_days", Float, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("prev_json", Text),  # card state before this review, for Undo
)
quiz_attempts = Table(
    "quiz_attempts", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("title", String(128), nullable=False),
    Column("mode", String(16), nullable=False),  # practice|mastery|sprint60|sprint120|burst
    Column("questions_json", Text, nullable=False),
    Column("total", Integer, nullable=False),
    Column("score", Integer),
    Column("passed", Integer),
    Column("xp_awarded", Integer, nullable=False, server_default="0"),
    Column("started_at", Integer, nullable=False),
    Column("deadline_at", Integer),
    Column("finished_at", Integer),
)
Index("ix_quiz_user", quiz_attempts.c.user_id, quiz_attempts.c.started_at)
quiz_details = Table(
    "quiz_details", metadata,
    Column("attempt_id", String(32), ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False),
    Column("idx", Integer, nullable=False),
    Column("answer", Text),
    Column("correct", Integer, nullable=False),
    Column("answered_at", Integer),
    UniqueConstraint("attempt_id", "idx"),
)
game_sessions = Table(
    "game_sessions", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("deck", String(16), nullable=False),
    Column("pairs_json", Text, nullable=False),
    Column("started_at", Integer, nullable=False),
    Column("finished_at", Integer),
    Column("moves", Integer),
    Column("misses", Integer),
    Column("seconds", Float),
    Column("xp_awarded", Integer, nullable=False, server_default="0"),
)
lesson_completions = Table(
    "lesson_completions", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("lesson", String(32), nullable=False),
    Column("completed_at", Integer, nullable=False),
    UniqueConstraint("user_id", "lesson"),
)
# xp_events.dedupe_key makes every award idempotent.
xp_events = Table(
    "xp_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("source", String(24), nullable=False),
    Column("dedupe_key", String(96), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("day", String(10), nullable=False),  # user-local YYYY-MM-DD
    Column("created_at", Integer, nullable=False),
    UniqueConstraint("user_id", "dedupe_key"),
)
Index("ix_xp_user_day", xp_events.c.user_id, xp_events.c.day)
activity = Table(
    "activity", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(24), nullable=False),
    Column("text", String(200), nullable=False),
    Column("created_at", Integer, nullable=False),
)
Index("ix_activity_user", activity.c.user_id, activity.c.created_at)
achievements = Table(
    "achievements", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("code", String(32), nullable=False),
    Column("unlocked_at", Integer, nullable=False),
    UniqueConstraint("user_id", "code"),
)
schema_migrations = Table(
    "schema_migrations", metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", Integer, nullable=False),
)

# ---------------------------------------------------------------- content
# Content tables are (re)built by scripts/build_content.py; the app only reads them.
kanji = Table(
    "kanji", metadata,
    Column("idx", Integer, primary_key=True),  # 1..2136 in KANJIDIC2 order
    Column("char", String(4), nullable=False, unique=True),
    Column("codepoint", String(8), nullable=False),
    Column("grade", Integer, nullable=False),  # 1-6, 8 = secondary school
    Column("strokes", Integer, nullable=False),
    Column("kvg_strokes", Integer),
    Column("freq", Integer),
    Column("jlpt_old", Integer),
    Column("meanings", Text, nullable=False),  # "; "-joined
    Column("onyomi", Text, nullable=False),
    Column("kunyomi", Text, nullable=False),
    Column("nanori", Text, nullable=False),
    Column("radical_num", Integer),
    Column("radical_char", String(4)),
    Column("radical_name", String(64)),
    Column("search_blob", Text, nullable=False),  # lower-case meanings+readings+romaji
)
Index("ix_kanji_grade", kanji.c.grade, kanji.c.idx)
Index("ix_kanji_strokes", kanji.c.strokes)
Index("ix_kanji_radical", kanji.c.radical_num)
kanji_vocab = Table(
    "kanji_vocab", metadata,
    Column("id", Integer, primary_key=True),
    Column("kanji", String(4), nullable=False, index=True),
    Column("word", String(32), nullable=False),
    Column("reading", String(64), nullable=False),
    Column("meaning", Text, nullable=False),
    Column("jmdict_id", String(12), nullable=False),
)
kanji_sentences = Table(
    "kanji_sentences", metadata,
    Column("id", Integer, primary_key=True),
    Column("kanji", String(4), nullable=False, index=True),
    Column("word", String(32), nullable=False),
    Column("jp", Text, nullable=False),
    Column("en", Text, nullable=False),
    Column("tatoeba_id", String(16), nullable=False),
)
kana_vocab = Table(
    "kana_vocab", metadata,
    Column("id", Integer, primary_key=True),
    Column("script", String(10), nullable=False),
    Column("word", String(32), nullable=False),
    Column("romaji", String(64), nullable=False),
    Column("kanji_form", String(32)),
    Column("meaning", Text, nullable=False),
    Column("pos", String(64), nullable=False),
    Column("category", String(24), nullable=False),
    Column("sentence_jp", Text),
    Column("sentence_en", Text),
    Column("tatoeba_id", String(16)),
    Column("jmdict_id", String(12), nullable=False),
    UniqueConstraint("script", "word"),
)
# Full JMdict (built by scripts/build_content.py). Searched via dict_forms (Japanese) and dict_fts (English).
dict_entries = Table(
    "dict_entries", metadata,
    Column("id", Integer, primary_key=True),  # JMdict entry sequence number
    Column("headword", String(64), nullable=False),
    Column("reading", String(64), nullable=False),
    Column("other_forms", Text, nullable=False, server_default=""),
    Column("common", Integer, nullable=False),
    Column("senses_json", Text, nullable=False),
    Column("sentence_jp", Text),
    Column("sentence_en", Text),
)
dict_forms = Table(
    "dict_forms", metadata,
    Column("entry_id", Integer, nullable=False),
    Column("form", String(64), nullable=False),
    Column("common", Integer, nullable=False),
)
Index("ix_dict_forms_form", dict_forms.c.form)
content_meta = Table(
    "content_meta", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

CONTENT_TABLES = [kanji, kanji_vocab, kanji_sentences, kana_vocab, dict_entries, dict_forms, content_meta]
SCHEMA_VERSION = 6
# Additive migrations: (version, table, column, DDL). Never drops or rewrites data.
# (Versions 2–3 added voice settings; sound was later removed. Older databases may still
#  have unused audio_speed / voice_* columns in `settings`. They are harmless and left alone.)
MIGRATIONS = [
    (4, "srs_cards", "deck_id", "ALTER TABLE srs_cards ADD COLUMN deck_id INTEGER REFERENCES decks(id) ON DELETE CASCADE"),
    (4, "srs_cards", "position", "ALTER TABLE srs_cards ADD COLUMN position INTEGER NOT NULL DEFAULT 0"),
    (4, "srs_cards", "suspended", "ALTER TABLE srs_cards ADD COLUMN suspended INTEGER NOT NULL DEFAULT 0"),
    (4, "srs_cards", "buried_until", "ALTER TABLE srs_cards ADD COLUMN buried_until INTEGER NOT NULL DEFAULT 0"),
    (4, "srs_cards", "introduced_at", "ALTER TABLE srs_cards ADD COLUMN introduced_at INTEGER"),
    (4, "reviews", "prev_json", "ALTER TABLE reviews ADD COLUMN prev_json TEXT"),
    (5, "custom_cards", "model_id", "ALTER TABLE custom_cards ADD COLUMN model_id INTEGER REFERENCES anki_models(id) ON DELETE SET NULL"),
    (5, "custom_cards", "fields_json", "ALTER TABLE custom_cards ADD COLUMN fields_json TEXT"),
    (5, "custom_cards", "ord", "ALTER TABLE custom_cards ADD COLUMN ord INTEGER NOT NULL DEFAULT 0"),
    (5, "custom_cards", "tags", "ALTER TABLE custom_cards ADD COLUMN tags VARCHAR(500) NOT NULL DEFAULT ''"),
    (5, "settings", "anki_autoplay", "ALTER TABLE settings ADD COLUMN anki_autoplay INTEGER NOT NULL DEFAULT 1"),
    (6, "settings", "palette", "ALTER TABLE settings ADD COLUMN palette VARCHAR(16) NOT NULL DEFAULT 'hanabi'"),
]


def count_if(cond):
    """SUM over a condition, always as an integer. (func.sum(a == b) would be typed Boolean and come back as True/False.)"""
    from sqlalchemy import case, func
    return func.sum(case((cond, 1), else_=0))


def make_engine(path: Path | str = DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # uri=True lets sync_content ATTACH the shipped content.db read-only (it may live on a read-only AppImage mount)
    eng = create_engine(f"sqlite:///{path.resolve().as_uri()}?uri=true", connect_args={"check_same_thread": False, "timeout": 15},
                        pool_size=8, max_overflow=8)
    eng.hanabi_path = path.resolve()  # the real file path (works on Linux and Windows)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn: sqlite3.Connection, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.execute("PRAGMA cache_size=-16000")
        cur.execute("PRAGMA mmap_size=134217728")
        cur.close()

    return eng


engine = make_engine()


def init_db(eng=None) -> None:
    eng = eng or engine
    metadata.create_all(eng)
    import time
    with eng.begin() as c:
        for _, table, col, ddl in MIGRATIONS:
            cols = {r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))}
            if col not in cols:
                c.execute(text(ddl))
        if c.execute(text("SELECT 1 FROM schema_migrations WHERE version=4")).first() is None:
            now = int(time.time())
            c.execute(text("""INSERT OR IGNORE INTO decks (user_id, name, new_per_day, max_reviews, created_at)
                              SELECT DISTINCT user_id, 'My kanji', 10, 200, :now FROM srs_cards WHERE track='kanji'"""), {"now": now})
            c.execute(text("""UPDATE srs_cards SET deck_id = (SELECT d.id FROM decks d WHERE d.user_id = srs_cards.user_id AND d.name='My kanji'),
                              position = COALESCE((SELECT k.idx FROM kanji k WHERE k.char = srs_cards.item), 0)
                              WHERE track='kanji' AND deck_id IS NULL"""))
            c.execute(text("""UPDATE srs_cards SET introduced_at = COALESCE(
                              (SELECT MIN(r.created_at) FROM reviews r WHERE r.card_id = srs_cards.id), last_review_at)
                              WHERE total_reviews > 0 AND introduced_at IS NULL"""))
        for v in range(1, SCHEMA_VERSION + 1):
            if c.execute(text("SELECT 1 FROM schema_migrations WHERE version=:v"), {"v": v}).first() is None:
                c.execute(schema_migrations.insert().values(version=v, applied_at=int(time.time())))
        # English search over the dictionary (FTS5, rowid = JMdict id). Built by build_content.
        c.execute(text(FTS_DDL))
    sync_content(eng)
    with eng.begin() as c:
        c.execute(text("PRAGMA optimize"))


FTS_DDL = "CREATE VIRTUAL TABLE IF NOT EXISTS dict_fts USING fts5(gloss, tokenize='unicode61 remove_diacritics 2')"


def sync_content(eng, src: Path | None = None) -> bool:
    """Copy the shipped content (content.db) into this database when it is newer.

    Only content tables are replaced; accounts and progress are never touched.
    Runs at startup, takes a few seconds once per content update.
    """
    src = Path(src or CONTENT_DB)
    if not src.exists() or src.resolve() == getattr(eng, "hanabi_path", None):
        return False
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("ATTACH DATABASE ? AS src", (f"{src.resolve().as_uri()}?mode=ro&immutable=1",))
        try:
            new = cur.execute("SELECT value FROM src.content_meta WHERE key='built_at'").fetchone()
            old = cur.execute("SELECT value FROM main.content_meta WHERE key='built_at'").fetchone()
            if not new or (old and old[0] == new[0]):
                return False
            cur.execute("BEGIN")
            for t in CONTENT_TABLES:
                cols = ", ".join(f'"{c.name}"' for c in t.columns)
                cur.execute(f'DELETE FROM main."{t.name}"')
                cur.execute(f'INSERT INTO main."{t.name}" ({cols}) SELECT {cols} FROM src."{t.name}"')
            cur.execute("DELETE FROM main.dict_fts")
            if cur.execute("SELECT 1 FROM src.sqlite_master WHERE name='dict_fts'").fetchone():
                cur.execute("INSERT INTO main.dict_fts(rowid, gloss) SELECT rowid, gloss FROM src.dict_fts")
            cur.execute("COMMIT")
            return True
        except Exception:
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            cur.execute("DETACH DATABASE src")
    finally:
        raw.close()


@contextmanager
def tx(eng=None):
    with (eng or engine).begin() as c:
        yield c


@contextmanager
def ro(eng=None):
    with (eng or engine).connect() as c:
        yield c
