"""Subtitles from OpenSubtitles.com, searched for one video at a time and chosen by the reader.

The REST API (opensubtitles.stoplight.io): an application key ('Api-Key'), a 'User-Agent' naming the app, and a
user's login for downloads (a token valid for a day; the daily quota comes with the account: 20 a day free,
1000 with VIP). Searches send the video's IMDb ID (the show's for an episode, with season and episode), the file's
moviehash (results that match it come first) and its name; parameters sorted, lower case, IDs without 'tt' or
leading zeros, as the API asks. Nothing is downloaded unless the reader picks a subtitle.
"""
from __future__ import annotations

import os
import re
import struct
import time

import requests

from . import __version__

API = "https://api.opensubtitles.com/api/v1/"
TOKEN_HOURS = 20  # a login token lasts a day; log in again a little before


class OpenSubtitlesError(Exception):
    """A sentence for the reader: what went wrong and what to do."""


def moviehash(path: str) -> str | None:
    """OpenSubtitles' file fingerprint: the size plus the 64-bit sums of the first and last 64 KB, as 16 hex digits."""
    try:
        size = os.path.getsize(path)
        if size < 131072:
            return None
        total = size
        with open(path, "rb") as f:
            for offset in (0, size - 65536):
                f.seek(offset)
                for (n,) in struct.iter_unpack("<Q", f.read(65536)):
                    total = (total + n) & 0xFFFFFFFFFFFFFFFF
        return f"{total:016x}"
    except OSError:
        return None


def _imdb_number(imdb_id: str | None) -> int | None:
    m = re.fullmatch(r"(?:tt)?0*(\d+)", str(imdb_id or ""))
    return int(m.group(1)) if m else None


def release_match(release: str, file_name: str) -> list[str]:
    """What a subtitle's release name has in common with the video's file name: the release group, the source and the
    resolution, the things that decide whether its timing fits ('RARBG', 'WEB-DL', '1080p')."""
    def words(s: str) -> set[str]:
        return {w for w in re.split(r"[\s._\-\[\]()]+", s.lower()) if w}

    a, b = words(release), words(os.path.splitext(file_name)[0])
    same = []
    # The group ends the name, after the last '-'; a video's extension ('.mkv') may follow, a codec ('.x265-') doesn't count.
    group = lambda s: (re.search(r"-([a-z0-9]+)(?:\.(?:mkv|mp4|avi|m4v|ts|srt))?$", s.lower()) or [None, None])[1]  # noqa: E731
    if group(release) and group(release) == group(file_name):
        same.append(f"group {group(file_name).upper()}")  # type: ignore[union-attr]
    for word, label in (("2160p", "2160p"), ("1080p", "1080p"), ("720p", "720p"), ("bluray", "BluRay"), ("web-dl", "WEB-DL"),
                        ("webdl", "WEB-DL"), ("webrip", "WEBRip"), ("hdtv", "HDTV"), ("dvdrip", "DVDRip"), ("amzn", "AMZN"),
                        ("nf", "NF"), ("dsnp", "DSNP"), ("hmax", "HMAX"), ("atvp", "ATVP")):
        if word in a and word in b and label not in same:
            same.append(label)
    return same


class OpenSubtitles:
    def __init__(self, api_key: str, user: str, password: str, store, timeout: float = 20):
        self.api_key, self.user, self.password, self.store, self.timeout = api_key, user, password, store, timeout
        self.session = requests.Session()
        self.session.headers.update({"Api-Key": api_key, "User-Agent": f"muthur v{__version__}", "Accept": "application/json"})

    def _token(self) -> str:
        """The login token, kept for most of a day: logging in is rate-limited (the API asks not to repeat it)."""
        saved = self.store.get("opensubtitles.session") or {}
        if saved.get("token") and saved.get("user") == self.user and time.time() - saved.get("at", 0) < TOKEN_HOURS * 3600:
            return saved["token"]
        r = self.session.post(API + "login", json={"username": self.user, "password": self.password}, timeout=self.timeout)
        if r.status_code == 401:
            raise OpenSubtitlesError("OpenSubtitles didn’t accept the account. Check the username and password in Settings.")
        if r.status_code == 403:
            raise OpenSubtitlesError("OpenSubtitles didn’t accept the API key. Check it in Settings.")
        r.raise_for_status()
        body = r.json()
        self.store.put("opensubtitles.session", {"token": body["token"], "user": self.user, "at": time.time(),
                                                 "allowed": (body.get("user") or {}).get("allowed_downloads"),
                                                 "level": (body.get("user") or {}).get("level"), "vip": (body.get("user") or {}).get("vip")})
        return body["token"]

    def check(self) -> dict:
        """{'ok': True, 'level': 'Sub leecher', 'allowed': 20} or {'ok': False, 'problem': '…'}."""
        try:
            self.store.put("opensubtitles.session", None)
            self._token()
            s = self.store.get("opensubtitles.session") or {}
            return {"ok": True, "level": s.get("level"), "allowed": s.get("allowed"), "vip": bool(s.get("vip"))}
        except OpenSubtitlesError as e:
            return {"ok": False, "problem": str(e)}
        except requests.RequestException as e:
            return {"ok": False, "problem": f"OpenSubtitles didn’t answer ({type(e).__name__})."}

    def search(self, *, imdb_id: str | None = None, parent_imdb_id: str | None = None, season: int | None = None,
               episode: int | None = None, video: str | None = None, languages: str = "en,nl") -> list[dict]:
        """Subtitles for one film (imdb_id) or one episode (the show's parent_imdb_id with season and episode), the ones
        matching the file's fingerprint first. Each with what helps choose: release, match, downloads, rating, flags."""
        params: dict = {"languages": languages}
        if parent_imdb_id and season is not None and episode is not None:
            params.update(parent_imdb_id=_imdb_number(parent_imdb_id), season_number=season, episode_number=episode, type="episode")
        elif imdb_id:
            params.update(imdb_id=_imdb_number(imdb_id), type="movie")
        if video and (h := moviehash(video)):
            params["moviehash"] = h
        if not any(k in params for k in ("imdb_id", "parent_imdb_id", "moviehash")):
            raise OpenSubtitlesError("muthur doesn’t know this video’s IMDb ID. Write its NFO first (Health, or the episode menu).")
        try:
            r = self.session.get(API + "subtitles", params=sorted(params.items()), timeout=self.timeout)
        except requests.RequestException as e:
            raise OpenSubtitlesError(f"OpenSubtitles didn’t answer ({type(e).__name__}). Try again in a moment.")
        if r.status_code == 429:
            raise OpenSubtitlesError("OpenSubtitles asks to slow down. Try again in a few seconds.")
        if r.status_code == 403:
            raise OpenSubtitlesError("OpenSubtitles didn’t accept the API key. Check it in Settings.")
        r.raise_for_status()
        name = os.path.basename(video or "")
        out = []
        for item in r.json().get("data", []):
            a = item.get("attributes") or {}
            files = a.get("files") or []
            if not files:
                continue
            release = a.get("release") or files[0].get("file_name") or ""
            out.append({
                "fileId": files[0]["file_id"], "language": a.get("language"), "release": release,
                "hashMatch": bool(a.get("moviehash_match")), "same": release_match(release, name) if name else [],
                "downloads": a.get("download_count") or 0, "rating": a.get("ratings") or 0, "votes": a.get("votes") or 0,
                "hearingImpaired": bool(a.get("hearing_impaired")), "forced": bool(a.get("foreign_parts_only")),
                "aiTranslated": bool(a.get("ai_translated")), "machineTranslated": bool(a.get("machine_translated")),
                "fps": a.get("fps") or None, "parts": a.get("nb_cd") or 1, "trusted": bool(a.get("from_trusted")),
                "uploader": ((a.get("uploader") or {}).get("name") or None), "rank": ((a.get("uploader") or {}).get("rank") or None),
                "uploaded": (a.get("upload_date") or "")[:10] or None, "comments": (a.get("comments") or "").strip()[:200] or None,
            })
        # The file's own fingerprint first, then the most in common with its name, then English, then the most downloaded.
        out.sort(key=lambda s: (not s["hashMatch"], -len(s["same"]), s["language"] != "en", s["machineTranslated"], -s["downloads"]))
        return out

    def download(self, file_id: int) -> tuple[bytes, int | None]:
        """The subtitle file as SRT, and how many downloads are left today."""
        def post(token: str):
            return self.session.post(API + "download", json={"file_id": int(file_id), "sub_format": "srt"},
                                     headers={"Authorization": f"Bearer {token}"}, timeout=self.timeout)
        r = post(self._token())
        if r.status_code == 401:  # the kept token ran out early: log in once more
            self.store.put("opensubtitles.session", None)
            r = post(self._token())
        if r.status_code == 406:
            raise OpenSubtitlesError("Today’s OpenSubtitles downloads are used up. They reset at midnight (UTC).")
        if r.status_code == 429:
            raise OpenSubtitlesError("OpenSubtitles asks to slow down. Try again in a few seconds.")
        r.raise_for_status()
        body = r.json()
        link = body.get("link")
        if not isinstance(link, str) or not link.startswith("https://"):
            raise OpenSubtitlesError("OpenSubtitles didn’t give a download link. Try another subtitle.")
        f = self.session.get(link, timeout=self.timeout)
        f.raise_for_status()
        return f.content, body.get("remaining")
