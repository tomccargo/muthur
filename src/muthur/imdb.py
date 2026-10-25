"""IMDb scores from IMDb's non-commercial datasets (ARCHITECTURE.md §8).

https://datasets.imdbws.com/ is refreshed daily; muthur reads it weekly. The data is for personal,
non-commercial use (https://data.imdb.com/non-commercial-datasets/). Both files are streamed and
filtered line by line: only rows for titles in the library are kept, so the 55 MB episode file
never sits in memory.
"""
from __future__ import annotations

import gzip
import io
import time

import requests

BASE = "https://datasets.imdbws.com/"
REFRESH_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS imdb_ratings (tconst TEXT PRIMARY KEY, rating REAL NOT NULL, votes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS imdb_episodes (tconst TEXT PRIMARY KEY, parent TEXT NOT NULL, season INTEGER, episode INTEGER);
CREATE INDEX IF NOT EXISTS imdb_episodes_by_show ON imdb_episodes (parent, season, episode);
"""


def _int(v: str) -> int | None:
    return int(v) if v.isdigit() else None  # IMDb writes a missing value as \N


def _rows(stream):
    """Fields of every line after the header of a gzipped TSV stream."""
    with gzip.GzipFile(fileobj=stream) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="\n")
        next(text, None)
        for line in text:
            yield line.rstrip("\n").split("\t")


class Imdb:
    def __init__(self, store, base: str = BASE, opener=None):
        """opener(url) -> a binary file object; tests pass local files instead of the network."""
        self.store, self.base = store, base
        self.opener = opener or self._download
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()

    @staticmethod
    def _download(url: str):
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        r.raw.decode_content = False  # the body is the .gz file itself; gzip reads it
        return r.raw

    # -- refresh ----------------------------------------------------------------------
    def refresh(self, shows: set[str], titles: set[str], job=None) -> dict:
        """Keep episode rows of `shows` and ratings of `shows`, `titles` and those episodes."""
        if job:
            job.total, job.done = 2, 0
        episodes = [(f[0], f[1], _int(f[2]), _int(f[3]))
                    for f in _rows(self.opener(self.base + "title.episode.tsv.gz")) if len(f) == 4 and f[1] in shows]
        if job:
            job.done = 1
        wanted = shows | titles | {e[0] for e in episodes}
        ratings = []
        for f in _rows(self.opener(self.base + "title.ratings.tsv.gz")):
            if len(f) == 3 and f[0] in wanted:
                try:
                    ratings.append((f[0], float(f[1]), int(f[2])))
                except ValueError:
                    continue
        with self.store.lock:  # one transaction: readers see the old set or the new one, never half
            db = self.store.db
            db.execute("DELETE FROM imdb_episodes")
            db.execute("DELETE FROM imdb_ratings")
            db.executemany("INSERT OR REPLACE INTO imdb_episodes VALUES (?, ?, ?, ?)", episodes)
            db.executemany("INSERT OR REPLACE INTO imdb_ratings VALUES (?, ?, ?)", ratings)
            db.commit()
        info = {"at": time.time(), "shows": len(shows), "titles": len(titles), "episodes": len(episodes), "ratings": len(ratings)}
        self.store.put("imdb.refreshed", info)
        if job:
            job.done = 2
        return info

    def refreshed(self) -> dict | None:
        return self.store.get("imdb.refreshed")

    def due(self) -> bool:
        info = self.refreshed()
        return not info or time.time() - info["at"] > REFRESH_DAYS * 86400

    # -- lookups ------------------------------------------------------------------------
    def _one(self, sql: str, args) -> tuple | None:
        with self.store.lock:
            return self.store.db.execute(sql, args).fetchone()

    def rating(self, tconst: str | None) -> tuple[float, int] | None:
        if not tconst:
            return None
        row = self._one("SELECT rating, votes FROM imdb_ratings WHERE tconst = ?", (tconst,))
        return (row[0], row[1]) if row else None

    def episode(self, show: str | None, season: int, episode: int, tmdb_count: int | None) -> tuple[float, int] | None:
        """The score of one episode, numbered as on TMDB. Left out (None) when IMDb counts a different
        number of episodes in that season: the numbering then differs, and the score could belong to
        another episode."""
        if not show:
            return None
        row = self._one("SELECT COUNT(*) FROM imdb_episodes WHERE parent = ? AND season = ?", (show, season))
        count = row[0] if row else 0
        if not count or (tmdb_count is not None and count != tmdb_count):
            return None
        row = self._one("SELECT r.rating, r.votes FROM imdb_episodes e JOIN imdb_ratings r ON r.tconst = e.tconst "
                        "WHERE e.parent = ? AND e.season = ? AND e.episode = ?", (show, season, episode))
        return (row[0], row[1]) if row else None

    def counts(self) -> dict:
        with self.store.lock:
            db = self.store.db
            return {"episodes": db.execute("SELECT COUNT(*) FROM imdb_episodes").fetchone()[0],
                    "ratings": db.execute("SELECT COUNT(*) FROM imdb_ratings").fetchone()[0]}
