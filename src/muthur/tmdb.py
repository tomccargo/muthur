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


class Tmdb:
    def __init__(self, token: str, cache_path: str, language: str = "en-US", max_per_second: float = 20.0):
        self.language = language
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL)")
        self.lock = threading.Lock()
        self.min_gap = 1.0 / max_per_second
        self.last = 0.0
        self.calls = 0
        self.hits = 0

    def get(self, path: str, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("language", self.language)
        key = f"{path}?{urlencode(sorted(params.items()))}"
        with self.lock:
            row = self.db.execute("SELECT body FROM cache WHERE key = ?", (key,)).fetchone()
        if row:
            self.hits += 1
            return json.loads(row[0])

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
        return self.get("/search/tv", query=query, first_air_date_year=year).get("results", [])

    def search_movie(self, query: str, year: int | None = None) -> list[dict]:
        return self.get("/search/movie", query=query, year=year).get("results", [])

    def tv(self, tv_id: int) -> dict:
        return self.get(f"/tv/{tv_id}", append_to_response="external_ids,alternative_titles")

    def movie(self, movie_id: int) -> dict:
        return self.get(f"/movie/{movie_id}", append_to_response="external_ids,alternative_titles")

    def find(self, external_id: str, source: str) -> dict:
        return self.get(f"/find/{external_id}", external_source=source)
