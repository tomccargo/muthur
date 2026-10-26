"""The library as it is on disk: shows, episodes and films, with what their NFOs say, their score
and whether they were watched. Read-only; the Library, Duplicates and Health pages read it.

NFOs are parsed once and cached by modification time and size, so a second index of a
library with thousands of NFOs reads only what changed.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict
from typing import Any

from .library import scan_film
from .nfo import NfoInfo, read_nfo
from .parse import BROKEN_EPISODE, EXTRA_NAME, SAMPLE, is_video
from .subtitles import language

NFO_PARSER = 3  # raise when nfo.py reads NFOs differently (2: double-episode NFOs, 0.39.3; 3: genres and plot, 0.42)
SCHEMA = "CREATE TABLE IF NOT EXISTS nfo_cache (path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, body TEXT NOT NULL);"
NUMBERS = re.compile(r"(?i)\bs(\d{1,3})((?:[ ._-]?e\d{1,3})+)")
ART = (".jpg", ".jpeg", ".png", ".tbn")
SUBTITLES = (".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup")
JUNK = re.compile(r"(?i)\.(txt|url|exe|scr|lnk|html?|nzb|torrent|part|!qb|dat|db)$")
KEEP = {"tvshow.nfo", "poster.jpg", "fanart.jpg", "clearlogo.png", "banner.jpg", "landscape.jpg", "clearart.png",
        "characterart.png", "logo.png", "theme.mp3", ".actors"}


def _sub_langs(stem: str, files: list[str]) -> list[str]:
    """Languages of the subtitles beside a video, from their names: 'x.en.srt' EN, 'x.English.srt' EN, 'x.srt' SUB."""
    out: list[str] = []
    for f in files:
        if not (f.startswith(stem + ".") and f.lower().endswith(SUBTITLES)):
            continue
        bare = os.path.splitext(f)[0]  # 'x.en.srt' -> 'x.en'; 'x.srt' -> 'x' (no tags)
        lang = language(bare[len(stem):]) if len(bare) > len(stem) else None
        label = lang.upper() if lang else "SUB"
        if label not in out:
            out.append(label)
    return out


def _numbers(name: str) -> tuple[int | None, list[int]]:
    m = NUMBERS.search(name)
    if not m:
        return None, []
    return int(m.group(1)), [int(n) for n in re.findall(r"\d+", m.group(2))]


class Index:
    def __init__(self, store, tv_root: str, film_root: str):
        self.store, self.tv_root, self.film_root = store, tv_root, film_root
        with store.lock:
            store.db.execute(SCHEMA)
            store.db.commit()
        if store.get("nfo.parser") != NFO_PARSER:  # NFOs are read differently now: what was cached is read again
            with store.lock:
                store.db.execute("DELETE FROM nfo_cache")
                store.db.commit()
            store.put("nfo.parser", NFO_PARSER)

    # -- NFOs, cached ------------------------------------------------------------------
    def nfo(self, path: str) -> NfoInfo | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        if st.st_size == 0:  # an empty NFO (some tools leave them) tells Kodi nothing: as good as none
            return None
        with self.store.lock:
            row = self.store.db.execute("SELECT mtime, size, body FROM nfo_cache WHERE path = ?", (path,)).fetchone()
        if row and row[0] == st.st_mtime and row[1] == st.st_size:
            d = json.loads(row[2])
            d["ratings"] = {k: tuple(v) for k, v in d["ratings"].items()}
            return NfoInfo(**d)
        try:
            info = read_nfo(path)
        except OSError:
            return None
        with self.store.lock:
            self.store.db.execute("INSERT OR REPLACE INTO nfo_cache VALUES (?, ?, ?, ?)", (path, st.st_mtime, st.st_size, json.dumps(asdict(info))))
            self.store.db.commit()
        return info

    # -- the whole library --------------------------------------------------------------
    def build(self, watched: dict | None = None, job=None) -> dict:
        """watched: Watched.latest() (key -> row), to mark what was watched."""
        played = _played(watched or {})
        shows = [] if not os.path.isdir(self.tv_root) else sorted(
            d for d in os.listdir(self.tv_root) if os.path.isdir(os.path.join(self.tv_root, d)) and not d.startswith((".", "@", "#")))
        if job:
            job.begin("Reading the TV and Film folders", len(shows) + 1)
        out_shows = []
        for folder in shows:
            out_shows.append(self._show(folder, played))
            if job:
                job.done += 1
        films = self._films(played)
        if job:
            job.done += 1
        return {"at": time.time(), "shows": out_shows, "films": films}

    def _show(self, folder: str, played: dict) -> dict:
        base = os.path.join(self.tv_root, folder)
        files: list[str] = []
        for dirpath, dirnames, names in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "@", "#"))]
            rel = os.path.relpath(dirpath, base)
            files += [n if rel == "." else f"{rel}/{n}".replace(os.sep, "/") for n in names]
        present = set(files)
        info = self.nfo(os.path.join(base, "tvshow.nfo")) if "tvshow.nfo" in present else None
        ids = info.ids if info else {}
        show: dict[str, Any] = {"folder": folder, "title": (info.title if info and info.title else folder), "year": info.year if info else None,
                "ids": ids, "nfo": bool(info and info.readable), "muthur": bool(info and info.muthur),
                "poster": "poster.jpg" in present, "fanart": "fanart.jpg" in present, "rating": _shown(info),
                "genres": info.genres if info else [], "plot": info.plot if info else None,
                "episodes": [], "loose": []}
        stems = set()
        for f in sorted(files):
            if not is_video(f):
                continue
            stem = f.rsplit(".", 1)[0]
            stems.add(stem)
            name = f.rsplit("/", 1)[-1]
            nfo = self.nfo(os.path.join(base, stem + ".nfo")) if stem + ".nfo" in present else None
            season, numbers = _numbers(name)
            if season is None and nfo and nfo.season is not None and nfo.episode is not None:
                season, numbers = nfo.season, [nfo.episode]
            extra = season is None and bool(EXTRA_NAME.search(name))  # "Trailer Park Boys S01E01" is an episode
            if season is None and not extra:
                # No SxxEyy: what the inbox reads (season folders and guessit, cached): 'Season 1/Magi - 01', 'Season 1/101'
                # (26 Oct: these were all questions). A number without a season stays without one: Health only takes it
                # when TMDB has a single season ('Death note - EP 1').
                p = self.store.parsed("episode", [folder, *f.split("/")])
                if p.episodes:
                    season, numbers = p.season, list(p.episodes)
            try:
                st = os.stat(os.path.join(base, f))
                size, added = st.st_size, int(st.st_mtime)
            except OSError:
                size, added = 0, 0
            ep = {"file": f, "size": size, "added": added, "season": season, "episodes": numbers, "nfo": bool(nfo and nfo.readable),
                  "muthur": bool(nfo and nfo.muthur), "title": nfo.title if nfo else None, "rating": _shown(nfo),
                  "imdb": list(nfo.ratings["imdb"]) if nfo and "imdb" in nfo.ratings else None,
                  "thumb": any(stem + s in present for s in ("-thumb.jpg", ".tbn", "-thumb.png")),
                  "subs": sum(1 for x in files if x.startswith(stem + ".") and x.lower().endswith(SUBTITLES)),
                  "subLangs": _sub_langs(stem, files),
                  "damaged": bool(BROKEN_EPISODE.search(name)), "sample": bool(SAMPLE.search(name)), "extra": extra,
                  "mismatch": bool(nfo and nfo.season is not None and nfo.episode is not None and season is not None
                                   and (nfo.season, nfo.episode) != (season, numbers[0] if numbers else None)),
                  "watched": _was_played(played, ids, season, numbers)}
            show["episodes"].append(ep)
        # Files that belong to no video: NFOs and thumbnails of episodes that are gone, and junk.
        for f in sorted(files):
            low = f.lower()
            if is_video(f) or f in KEEP or low.endswith(SUBTITLES) or re.match(r"(?i)^season(\d+|-specials|-all)-(poster|banner|fanart|landscape)\.(jpg|png)$", f.rsplit("/", 1)[-1]):
                continue
            stem = re.sub(r"(?i)(-thumb)?\.(nfo|jpg|jpeg|png|tbn)$", "", f)
            if (low.endswith((".nfo",) + ART) and stem not in stems and "/" in f) or JUNK.search(f) or _twin(f, present):
                show["loose"].append(f)
        return show

    def _films(self, played: dict) -> list[dict]:
        if not os.path.isdir(self.film_root):
            return []
        out = []
        for unit in scan_film(self.film_root):
            info = self.nfo(unit.nfo) if unit.nfo else None
            ids = info.ids if info else {}
            out.append({
                "key": unit.key, "folder": unit.folder, "file": "/".join(unit.main.parts) if unit.main else None,
                "size": unit.main.size if unit.main else 0, "others": ["/".join(o.parts) for o in unit.others],
                "title": info.title if info and info.title else unit.key, "year": info.year if info else None,
                "ids": ids, "nfo": bool(info and info.readable), "muthur": bool(info and info.muthur), "rating": _shown(info),
                "imdb": list(info.ratings["imdb"]) if info and "imdb" in info.ratings else None,
                "poster": bool(unit.folder and unit.main and os.path.isfile(os.path.join(self.film_root, *unit.main.parts[:-1], "poster.jpg"))),
                "flags": unit.flags, "watched": _was_played(played, ids, None, []),
                "nfoFile": os.path.relpath(unit.nfo, self.film_root).replace(os.sep, "/") if unit.nfo else None,
                "twins": _twins_of(unit.nfo),
                "genres": info.genres if info else [], "plot": info.plot if info else None,
                "added": _mtime(os.path.join(self.film_root, *unit.main.parts)) if unit.main else 0,
                "posterFile": _poster_of(self.film_root, unit.main.parts) if unit.main else None,
            })
        return out


def _poster_of(root: str, parts: list[str]) -> str | None:
    """The image Kodi takes as a film's poster, relative to the Film folder: 'poster.jpg' or 'folder.jpg' in a film's own
    folder, else '<video name>-poster.jpg' beside it."""
    stem = os.path.splitext(parts[-1])[0]
    try:
        names = set(os.listdir(os.path.join(root, *parts[:-1])))
    except OSError:
        return None
    own = ["poster.jpg", "poster.png", "folder.jpg"] if len(parts) > 1 else []
    found = next((n for n in [*own, f"{stem}-poster.jpg", f"{stem}-poster.png"] if n in names), None)
    return "/".join([*parts[:-1], found]) if found else None


def _mtime(path: str) -> int:
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return 0


def _twin(f: str, present: set[str]) -> bool:
    """'x.NFO' beside 'x.nfo': a download's release notes. Kodi reads the share without regard to case, so either
    one could be the NFO it gets."""
    return f.lower().endswith(".nfo") and not f.endswith(".nfo") and f[:-4] + ".nfo" in present


def _twins_of(nfo: str | None) -> list[str]:
    """The other files named like a film's NFO but for case ('x.NFO' beside 'x.nfo'), by name."""
    if not nfo or not nfo.endswith(".nfo"):
        return []
    folder, name = os.path.split(nfo)
    try:
        return sorted(n for n in os.listdir(folder) if n != name and n.lower() == name.lower())
    except OSError:
        return []


def _shown(info: NfoInfo | None) -> list | None:
    """The score Kodi shows for an item: [source, value, votes]."""
    if not info or not info.ratings:
        return None
    name = info.default_rating if info.default_rating in info.ratings else next(iter(info.ratings))
    value, votes = info.ratings[name]
    return [name, value, votes]


def _played(latest: dict) -> dict:
    """Play counts by every ID a backup row knows: ('tmdb', '2316', 4, 19) -> 1, ('imdb', 'tt0069293', None, None) -> 2."""
    out: dict = {}
    for row in latest.values():
        for kind, value in json.loads(row["ids"]).items():
            key = (kind, str(value), row["season"], row["episode"])
            out[key] = max(out.get(key, 0), row["playcount"])
    return out


def _was_played(played: dict, ids: dict, season, numbers) -> int | None:
    """The play count Kodi had at the last backup, or None when the backup doesn't know the item."""
    found = None
    for kind in ("tmdb", "imdb", "tvdb"):
        if ids.get(kind):
            for n in numbers or [None]:
                v = played.get((kind, str(ids[kind]), season, n))
                if v is not None:
                    found = max(found or 0, v)
    return found
