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
CREATE TABLE IF NOT EXISTS choices (    -- what the reader chose in Review, per download
    item TEXT PRIMARY KEY, body TEXT NOT NULL, saved REAL NOT NULL
);
"""


# Changes to an existing database, oldest first; a new database is created at the newest schema and
# starts past them. PRAGMA user_version counts the ones that ran. Never edit or reorder one that shipped.
MIGRATIONS: list[str] = []


def alias_key(title: str) -> str:
    return strip_article(normalize(title))


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # WAL with normal sync: a commit no longer waits for the disk to flush. On a NAS with
        # spinning disks a flush per commit made the library import take over an hour.
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.lock = threading.Lock()
        with self.lock:
            fresh = not self.db.execute("SELECT name FROM sqlite_master WHERE name = 'settings'").fetchone()
            self.db.executescript(SCHEMA)
            if fresh:
                self.db.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
            self.db.commit()

    def migrate(self) -> int:
        """Run the migrations this database hasn't had, after every module created its tables. Returns how many ran."""
        with self.lock:
            done = self.db.execute("PRAGMA user_version").fetchone()[0]
            for n, script in enumerate(MIGRATIONS[done:], start=done + 1):
                self.db.executescript(script)
                self.db.execute(f"PRAGMA user_version = {n}")
            self.db.commit()
        return max(0, len(MIGRATIONS) - done)

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
                 folder: str | None, source: str) -> tuple[str, str, int]:
        """Add or refresh an entry. A choice confirmed in Review is never downgraded to 'library'."""
        key = (kind, alias_key(title), tmdb_id)
        with self.lock:
            self.db.execute(
                """INSERT INTO aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (kind, norm, tmdb_id) DO UPDATE SET
                     year = excluded.year, title = excluded.title, folder = excluded.folder,
                     source = CASE WHEN aliases.source = 'confirmed' THEN 'confirmed' ELSE excluded.source END""",
                (*key, year, tmdb_title, folder, source, time.time()))
            self.db.commit()
        return key

    def forget_library_except(self, kind: str, keep: set[tuple[str, str, int]]) -> int:
        """Drop entries learned from the library that the latest full run didn't confirm again
        (folder gone or renamed, NFO now disagrees). Entries confirmed in Review stay."""
        with self.lock:
            rows = self.db.execute("SELECT kind, norm, tmdb_id FROM aliases WHERE kind = ? AND source = 'library'", (kind,)).fetchall()
            stale = [tuple(r) for r in rows if tuple(r) not in keep]
            self.db.executemany("DELETE FROM aliases WHERE kind = ? AND norm = ? AND tmdb_id = ?", stale)
            self.db.commit()
        return len(stale)

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

    def folder_for(self, kind: str, tmdb_id: int) -> str | None:
        """The library folder a remembered show lives in, if muthur knows one."""
        with self.lock:
            row = self.db.execute("SELECT folder FROM aliases WHERE kind = ? AND tmdb_id = ? AND folder IS NOT NULL "
                                  "ORDER BY source = 'library' DESC LIMIT 1", (kind, tmdb_id)).fetchone()
        return row["folder"] if row else None

    def tmdb_for_folder(self, kind: str, folder: str) -> int | None:
        """The TMDB ID muthur remembers for a library folder, if any."""
        with self.lock:
            row = self.db.execute("SELECT tmdb_id FROM aliases WHERE kind = ? AND folder = ? LIMIT 1", (kind, folder)).fetchone()
        return row["tmdb_id"] if row else None

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

    # -- choices made in Review ------------------------------------------------
    def choice(self, item: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM choices WHERE item = ?", (item,)).fetchone()
        return json.loads(row["body"]) if row else None

    def choose(self, item: str, body: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO choices VALUES (?, ?, ?)", (item, json.dumps(body), time.time()))
            self.db.commit()

    def forget_choice(self, item: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM choices WHERE item = ?", (item,))
            self.db.commit()

    def prune_choices(self, keep: set[str]) -> int:
        """Drop choices for downloads that are gone (applied, or removed by hand)."""
        with self.lock:
            stale = [r["item"] for r in self.db.execute("SELECT item FROM choices").fetchall() if r["item"] not in keep]
            self.db.executemany("DELETE FROM choices WHERE item = ?", [(s,) for s in stale])
            self.db.commit()
        return len(stale)

    # -- snapshots (last scan results etc.) ----------------------------------
    def save_snapshot(self, name: str, body) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)", (name, json.dumps(body), time.time()))
            self.db.commit()

    def snapshot_count(self, name: str, path: str, each: bool = False) -> int:
        """The length of a list inside a snapshot, counted by SQLite without loading the snapshot into Python.
        each: `path` holds an object of lists, and their lengths are added up."""
        q = ("SELECT COALESCE(SUM(json_array_length(j.value)), 0) FROM snapshots, json_each(snapshots.body, ?) j WHERE name = ?"
             if each else "SELECT COALESCE(json_array_length(body, ?), 0) FROM snapshots WHERE name = ?")
        with self.lock:
            row = self.db.execute(q, (path, name)).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def snapshot_saved(self, name: str) -> float | None:
        """When a snapshot was last saved, without loading it."""
        with self.lock:
            row = self.db.execute("SELECT saved FROM snapshots WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def snapshot(self, name: str):
        with self.lock:
            row = self.db.execute("SELECT body, saved FROM snapshots WHERE name = ?", (name,)).fetchone()
        return (json.loads(row["body"]), row["saved"]) if row else (None, None)
