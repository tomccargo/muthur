"""Small TMDB v3 client with an on-disk cache.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from urllib.parse import urlencode

import requests

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/"  # sizes from /configuration: posters w780, backdrops w1280, logos w500

DAY = 86400
FINISHED = {"Ended", "Canceled"}


def _show_max_age(body: dict) -> float | None:
    """A running show changes (new seasons, new episodes); a finished one doesn't."""
    return None if body.get("status") in FINISHED else DAY


def _season_max_age(body: dict) -> float | None:
    """A season with undated, upcoming or recent episodes still changes; an old complete one doesn't."""
    episodes = body.get("episodes") or []
    if not episodes:
        return DAY
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * DAY))
    if any(not e.get("air_date") or e["air_date"] >= cutoff for e in episodes):
        return DAY
    return None


def _search_max_age(body: dict) -> float | None:
    """Nothing found today may exist tomorrow; found results stay good for a month."""
    return DAY if not body.get("results") else 30 * DAY


class Tmdb:
    def __init__(self, token: str, cache_path: str, language: str = "en-US", max_per_second: float = 20.0):
        self.language = language
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")  # see Store: no flush per cached answer
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL)")
        self.lock = threading.Lock()
        self.min_gap = 1.0 / max_per_second
        self.last = 0.0
        self.calls = 0
        self.hits = 0

    def get(self, path: str, max_age=None, **params) -> dict:
        """max_age: seconds a cached answer stays valid, or a function of the cached answer that
        returns them (None: valid forever)."""
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("language", self.language)
        key = f"{path}?{urlencode(sorted(params.items()))}"
        with self.lock:
            row = self.db.execute("SELECT body, fetched FROM cache WHERE key = ?", (key,)).fetchone()
        if row:
            body = json.loads(row[0])
            limit = max_age(body) if callable(max_age) else max_age
            if limit is None or time.time() - row[1] < limit:
                self.hits += 1
                return body

        for attempt in range(5):
            with self.lock:
                wait = self.last + self.min_gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()
            r = self.session.get(API + path, params=params, timeout=30)
            self.calls += 1
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code == 404:
                body = {}
                break
            r.raise_for_status()
            body = r.json()
            break
        else:
            r.raise_for_status()
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, json.dumps(body), time.time()))
            self.db.commit()
        return body

    def search_tv(self, query: str, year: int | None = None) -> list[dict]:
        return self.get("/search/tv", max_age=_search_max_age, query=query, first_air_date_year=year).get("results", [])

    def search_movie(self, query: str, year: int | None = None) -> list[dict]:
        return self.get("/search/movie", max_age=_search_max_age, query=query, year=year).get("results", [])

    def tv(self, tv_id: int) -> dict:
        return self.get(f"/tv/{tv_id}", max_age=_show_max_age, append_to_response="external_ids,alternative_titles")

    def movie(self, movie_id: int) -> dict:
        return self.get(f"/movie/{movie_id}", max_age=30 * DAY, append_to_response="external_ids,alternative_titles")

    # Fuller answers for writing NFOs (cast, crew, logos); separate cache entries from the lookups above.
    def tv_full(self, tv_id: int) -> dict:
        return self.get(f"/tv/{tv_id}", max_age=_show_max_age, include_image_language="en,null",
                        append_to_response="external_ids,aggregate_credits,images")

    def movie_full(self, movie_id: int) -> dict:
        return self.get(f"/movie/{movie_id}", max_age=30 * DAY, include_image_language="en,null",
                        append_to_response="external_ids,credits,images")

    def image(self, path: str | None, size: str) -> bytes | None:
        """An image from TMDB's image server; it goes straight to disk, not into the cache."""
        if not path:
            return None
        r = self.session.get(f"{IMAGES}{size}{path}", timeout=60)
        return r.content if r.status_code == 200 and r.content else None

    def tv_season(self, tv_id: int, season: int) -> dict:
        return self.get(f"/tv/{tv_id}/season/{season}", max_age=_season_max_age)

    def find(self, external_id: str, source: str) -> dict:
        return self.get(f"/find/{external_id}", external_source=source)
