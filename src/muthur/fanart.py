"""Small fanart.tv client (API v3, https://fanarttv.docs.apiary.io) with an on-disk cache.

fanart.tv has the artwork TMDB doesn't: banners, landscapes (fanart with the title on it), clear art, character art
and disc art, and logos and season art where TMDB has none. Films are asked by their TMDB ID, shows by their TVDB ID.
A project key ('api-key') is needed; a personal key ('client-key') is optional and gets new images after 2 days
instead of 7. Images come from fanart.tv's own image server.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from urllib.parse import urlparse

import requests

API = "https://webservice.fanart.tv/v3"
DAY = 86400.0
TEXT_ORDER = {"en": 0, "00": 1, "": 1}  # English first, then without words, then any other language


def best(images: list[dict] | None, season: int | None = None) -> str | None:
    """The image to use: English, then one without language, then any; the most liked first. season: only that
    season's ('0' is the specials; 'all' never counts)."""
    if season is not None:
        images = [i for i in images or [] if str(i.get("season", "")) == str(season)]
    ranked = sorted(images or [], key=lambda i: (TEXT_ORDER.get(i.get("lang") or "", 2), -int(i.get("likes") or 0)))
    return next((i["url"] for i in ranked if _ours(i.get("url"))), None)


def _ours(url: str | None) -> bool:
    """Only images on fanart.tv's own servers are downloaded."""
    if not url:
        return False
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "").endswith("fanart.tv")


class FanartTv:
    def __init__(self, api_key: str, client_key: str | None, cache_path: str, max_per_second: float = 4.0):
        self.session = requests.Session()
        self.session.headers.update({"api-key": api_key, "Accept": "application/json"})
        if client_key:
            self.session.headers["client-key"] = client_key
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL)")
        self.lock = threading.Lock()
        self.min_gap = 1.0 / max_per_second
        self.last = 0.0

    def get(self, kind: str, item_id: int | str) -> dict:
        """kind 'movies' (TMDB ID) or 'tv' (TVDB ID). Found: kept 30 days; nothing yet: asked again after 7."""
        key = f"/{kind}/{item_id}"
        with self.lock:
            row = self.db.execute("SELECT body, fetched FROM cache WHERE key = ?", (key,)).fetchone()
        if row:
            body = json.loads(row[0])
            if time.time() - row[1] < (30 * DAY if body else 7 * DAY):
                return body
        for attempt in range(4):
            with self.lock:
                wait = self.last + self.min_gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()
            r = self.session.get(API + key, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code == 404:
                body = {}
                break
            r.raise_for_status()
            data = r.json()
            body = data if isinstance(data, dict) else {}
            break
        else:
            r.raise_for_status()
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, json.dumps(body), time.time()))
            self.db.commit()
        return body

    def movie(self, tmdb_id: int) -> dict:
        return self.get("movies", tmdb_id)

    def show(self, tvdb_id: int) -> dict:
        return self.get("tv", tvdb_id)

    def image(self, url: str | None) -> bytes | None:
        if not url or not _ours(url):
            return None
        r = self.session.get(url, timeout=60)
        return r.content if r.status_code == 200 and r.content else None

    def check(self) -> dict:
        """Settings' test: one known film (The Matrix, TMDB 603) with both keys."""
        try:
            r = self.session.get(f"{API}/movies/603", timeout=15)
        except requests.RequestException as e:
            return {"ok": False, "problem": f"fanart.tv didn't answer ({type(e).__name__})."}
        if r.status_code in (401, 403):
            return {"ok": False, "problem": "fanart.tv refused the key: check the project key (and the personal key, if you gave one)."}
        if r.status_code != 200:
            return {"ok": False, "problem": f"fanart.tv answered {r.status_code}."}
        return {"ok": True}
