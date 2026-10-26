"""Read IDs and a few facts from existing Kodi (or Sonarr/Emby/tinyMediaManager) NFO files. Read-only."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_IMDB = re.compile(r"\btt\d{6,9}\b")
_TMDB_URL = re.compile(r"themoviedb\.org/(?:movie|tv)/(\d+)")
_TVDB_URL = re.compile(r"thetvdb\.com/\?.*?id=(\d+)|thetvdb\.com/series/(\d+)")
_KNOWN = {"imdb", "tmdb", "tvdb", "tvmaze", "sonarr"}


@dataclass
class NfoInfo:
    ids: dict[str, str] = field(default_factory=dict)
    title: str | None = None
    year: int | None = None
    duration_s: int | None = None
    kind: str | None = None  # root tag: movie, tvshow, episodedetails
    readable: bool = True
    ratings: dict[str, tuple[float, int]] = field(default_factory=dict)  # 'imdb': (8.4, 41000)
    default_rating: str | None = None  # the rating Kodi shows
    season: int | None = None
    episode: int | None = None
    muthur: bool = False  # written by muthur
    genres: list[str] = field(default_factory=list)
    plot: str | None = None
    aired: str | None = None  # '2017-01-17': an episode's <aired>, else <premiered>


def _text(root, tag):
    el = root.find(tag)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def parse_nfo_text(text: str) -> NfoInfo:
    info = NfoInfo()
    start = text.find("<")
    try:
        root = ET.fromstring(text[start:] if start > 0 else text)
    except ET.ParseError:
        root = None
        # Kodi's NFO for a double episode holds one <episodedetails> per episode, so it has two roots: read the first.
        if m := re.search(r"<episodedetails\b.*?</episodedetails>", text, re.S):
            try:
                root = ET.fromstring(m.group(0))
            except ET.ParseError:
                root = None

    if root is None:
        # A "URL nfo" or a scene .nfo: pick IDs out of the text.
        info.readable = False
        if m := _IMDB.search(text):
            info.ids["imdb"] = m.group(0)
        if m := _TMDB_URL.search(text):
            info.ids["tmdb"] = m.group(1)
        if m := _TVDB_URL.search(text):
            info.ids["tvdb"] = m.group(1) or m.group(2)
        return info

    info.kind = root.tag.lower()
    info.muthur = "written by muthur" in text[:400]
    info.title = _text(root, "title")
    info.genres = list(dict.fromkeys(g.text.strip() for g in root.findall("genre") if g.text and g.text.strip()))
    info.plot = _text(root, "plot") or _text(root, "outline")
    for tag in ("season", "episode"):
        v = _text(root, tag)
        if v and v.lstrip("-").isdigit():
            setattr(info, tag, int(v))
    for r in root.findall("ratings/rating"):
        name = (r.get("name") or "").lower().strip()
        try:
            info.ratings[name] = (float(_text(r, "value") or ""), int(float(_text(r, "votes") or 0)))
        except ValueError:
            continue
        if r.get("default") == "true":
            info.default_rating = name
    if not info.ratings and (v := _text(root, "rating")):  # the old single <rating> tag
        try:
            info.ratings["default"] = (float(v), int(float(_text(root, "votes") or 0)))
            info.default_rating = "default"
        except ValueError:
            pass
    year = _text(root, "year") or (_text(root, "premiered") or "")[:4]
    info.year = int(year) if year and year.isdigit() else None
    info.aired = _text(root, "aired") or _text(root, "premiered")

    for el in root.findall("uniqueid"):
        typ = (el.get("type") or "").lower().strip()
        val = (el.text or "").strip()
        if typ in {"themoviedb", "tmdbid"}:
            typ = "tmdb"
        if typ and val and typ != "default":
            info.ids.setdefault(typ, val)

    # Older and non-Kodi tag styles.
    for tag, typ in (("imdbid", "imdb"), ("imdb_id", "imdb"), ("tmdbid", "tmdb"), ("tvdbid", "tvdb")):
        if (v := _text(root, tag)) and typ not in info.ids:
            info.ids[typ] = v
    legacy = _text(root, "id")
    if legacy and not (info.ids.keys() & {"imdb", "tmdb", "tvdb"}):
        if legacy.startswith("tt"):
            info.ids["imdb"] = legacy
        elif legacy.isdigit():
            info.ids["tvdb" if info.kind == "tvshow" else "tmdb"] = legacy
    if "imdb" not in info.ids and (m := _IMDB.search(text)):
        info.ids["imdb"] = m.group(0)

    dur = root.find("fileinfo/streamdetails/video/durationinseconds")
    if dur is not None and dur.text and dur.text.strip().isdigit():
        info.duration_s = int(dur.text.strip())
    elif (rt := _text(root, "runtime")) and rt.isdigit():  # minutes, as TMDB gives them
        info.duration_s = int(rt) * 60
    return info


def read_nfo(path: str) -> NfoInfo:
    with open(path, "rb") as f:
        raw = f.read(2_000_000)
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return parse_nfo_text(text)
