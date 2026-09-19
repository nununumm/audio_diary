"""SQLite database: connection management, schema, and full-text search.

Uses FTS5 with the ``trigram`` tokenizer, which works well for Japanese
(substring matching) without needing a language-specific word segmenter.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .config import get_settings

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date  TEXT NOT NULL,                 -- YYYY-MM-DD
    raw_text    TEXT NOT NULL DEFAULT '',      -- verbatim transcript
    clean_text  TEXT NOT NULL DEFAULT '',      -- AI-cleaned diary body
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(entry_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    storage_key TEXT NOT NULL,
    thumb_key   TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_photos_entry ON photos(entry_id);
"""

# Full-text search over both raw and cleaned text. Requires SQLite built with
# FTS5 + the trigram tokenizer (SQLite >= 3.34). If unavailable we fall back to
# LIKE-based search (see FTS_ENABLED and app.main.list_entries).
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    raw_text,
    clean_text,
    content='entries',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, raw_text, clean_text)
    VALUES (new.id, new.raw_text, new.clean_text);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, raw_text, clean_text)
    VALUES ('delete', old.id, old.raw_text, old.clean_text);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, raw_text, clean_text)
    VALUES ('delete', old.id, old.raw_text, old.clean_text);
    INSERT INTO entries_fts(rowid, raw_text, clean_text)
    VALUES (new.id, new.raw_text, new.clean_text);
END;
"""

# Set by init_db(): whether FTS5 full-text search is available.
FTS_ENABLED = False


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    # check_same_thread=False: FastAPI may create the connection (in a sync
    # dependency) and use it (in the endpoint) on different threads. Each request
    # gets its own connection and never shares it, so this is safe here.
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db() -> None:
    """Create tables/indexes if they do not exist; enable FTS if supported."""
    global FTS_ENABLED
    conn = _connect()
    try:
        conn.executescript(BASE_SCHEMA)
        try:
            conn.executescript(FTS_SCHEMA)
            # Verify the trigram tokenizer actually works (some builds have FTS5
            # but not trigram).
            conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
            FTS_ENABLED = True
        except sqlite3.Error as exc:
            FTS_ENABLED = False
            print(f"[db] FTS5 unavailable ({exc}); using LIKE-based search.")
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: yields a connection and commits/rolls back."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
