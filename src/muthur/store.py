"""muthur's own SQLite database in /config: settings and the ID memory."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from .text import normalize, strip_article

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS aliases (
    kind TEXT NOT NULL,          -- 'tv' | 'movie'
    norm TEXT NOT NULL,          -- normalised title, without a leading article
    tmdb_id INTEGER NOT NULL,
    year INTEGER,
    title TEXT NOT NULL,         -- TMDB title, for display
    folder TEXT,                 -- existing library folder, when there is one
    source TEXT NOT NULL,        -- 'library' (verified against TMDB) | 'confirmed' (chosen in Review)
    created REAL NOT NULL,
    PRIMARY KEY (kind, norm, tmdb_id)
);
CREATE TABLE IF NOT EXISTS parse_cache (key TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (name TEXT PRIMARY KEY, body TEXT NOT NULL, saved REAL NOT NULL);
"""


def alias_key(title: str) -> str:
    return strip_article(normalize(title))


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    # -- settings -----------------------------------------------------------
    def get(self, key: str, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def put(self, key: str, value) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
            self.db.commit()

    # -- ID memory ----------------------------------------------------------
    def remember(self, kind: str, title: str, tmdb_id: int, year: int | None, tmdb_title: str,
                 folder: str | None, source: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (kind, alias_key(title), tmdb_id, year, tmdb_title, folder, source, time.time()))
            self.db.commit()

    def lookup(self, kind: str, title: str, year: int | None = None) -> list[dict]:
        """Remembered entries for a title. More than one means the title is ambiguous."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM aliases WHERE kind = ? AND norm = ?", (kind, alias_key(title))).fetchall()
        found = {r["tmdb_id"]: dict(r) for r in rows}
        if year is not None:
            same_year = {k: v for k, v in found.items() if v["year"] == year}
            if same_year:
                return list(same_year.values())
        return list(found.values())

    def alias_count(self, kind: str | None = None) -> int:
        with self.lock:
            q = "SELECT COUNT(DISTINCT tmdb_id) FROM aliases" + (" WHERE kind = ?" if kind else "")
            return self.db.execute(q, (kind,) if kind else ()).fetchone()[0]

    # -- parse cache: each name is parsed once per parser version ---------------
    def parsed(self, kind: str, parts: list[str]):
        from dataclasses import asdict

        from .parse import PARSER_VERSION, Parsed, parse_episode, parse_movie

        key = f"{PARSER_VERSION}|{kind}|" + "/".join(parts)
        with self.lock:
            row = self.db.execute("SELECT body FROM parse_cache WHERE key = ?", (key,)).fetchone()
        if row:
            return Parsed(**json.loads(row["body"]))
        result = parse_episode(parts) if kind == "episode" else parse_movie(parts)
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO parse_cache VALUES (?, ?)", (key, json.dumps(asdict(result), default=str)))
            self.db.commit()
        return result

    # -- snapshots (last scan results etc.) ----------------------------------
    def save_snapshot(self, name: str, body) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)", (name, json.dumps(body), time.time()))
            self.db.commit()

    def snapshot(self, name: str):
        with self.lock:
            row = self.db.execute("SELECT body, saved FROM snapshots WHERE name = ?", (name,)).fetchone()
        return (json.loads(row["body"]), row["saved"]) if row else (None, None)
