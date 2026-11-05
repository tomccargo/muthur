"""The artwork Kodi shows, beside the video or in the item's folder (Kodi wiki: Artwork/Episode, Movie artwork,
TV-Show artwork, Season artwork): what is missing, and where muthur gets it. TMDB first (backdrops, logos, season
posters, episode stills); fanart.tv for the kinds TMDB doesn't have (banner, landscape, clear art, character art,
disc art), and where TMDB has none.

Decided 27 Oct: muthur only wrote artwork together with a new NFO, so whatever came with another tool's NFO never got
any (on the NAS: 138 episodes without a thumbnail, 461 films without fanart). Now each missing file is a fix of its
own. A file that is there is never replaced here; a poor poster is the 'posters' fix.

Found 5 Nov: a film's art is named after its video ('X (1999)-poster.jpg'). Kodi takes a plain 'poster.jpg' in a
film's folder only when the source has "Movies are in separate folders that match the movie title" on (Kodi 21,
VideoInfoScanner::GetArtwork: the folder is searched only with the source's useFolderNames); without it 58 films
showed a frame of the video. Plain names muthur wrote before are renamed by Health ('film-art').
"""
from __future__ import annotations

import os

import requests

from . import nfo_write
from .fanart import best

# (file name, TMDB field or 'logo', TMDB size, fanart.tv key)
SHOW = (("fanart.jpg", "backdrop_path", "w1280", "showbackground"), ("clearlogo.png", "logo", "w500", "hdtvlogo"),
        ("banner.jpg", None, None, "tvbanner"), ("landscape.jpg", None, None, "tvthumb"),
        ("clearart.png", None, None, "hdclearart"), ("characterart.png", None, None, "characterart"))
SEASON = (("poster", "poster_path", "w780", "seasonposter"), ("banner", None, None, "seasonbanner"),
          ("landscape", None, None, "seasonthumb"))
FILM = (("fanart.jpg", "backdrop_path", "w1280", "moviebackground"), ("clearlogo.png", "logo", "w500", "hdmovielogo"),
        ("banner.jpg", None, None, "moviebanner"), ("landscape.jpg", None, None, "moviethumb"),
        ("clearart.png", None, None, "hdmovieclearart"), ("discart.png", None, None, "moviedisc"))
WHAT = {"fanart": "fanart", "clearlogo": "clear logo", "banner": "banner", "landscape": "landscape", "clearart": "clear art",
        "characterart": "character art", "discart": "disc art", "poster": "poster"}


def plain_film_art(names: set[str], stem: str) -> list[tuple[str, str]]:
    """[(plain name, name after the video)] for the art in a film's folder that Kodi doesn't read: 'poster.jpg' to
    'X (1999)-poster.jpg', 'folder.jpg' to its poster when there is no other. One that has its named twin stays."""
    have = {n.lower() for n in names}
    out: list[tuple[str, str]] = []
    for kind in (*WHAT, "keyart", "folder"):
        to = "poster" if kind == "folder" else kind
        if any(f"{stem}-{to}{e}".lower() in have for e in (".jpg", ".png")) or any(t == to for _, t in out):
            continue
        plain = next((n for n in sorted(names) if n.lower() in (f"{kind}.jpg", f"{kind}.png")), None)
        if plain:
            out.append((plain, to))
    return [(n, f"{stem}-{to}{os.path.splitext(n)[1].lower()}") for n, to in out]


def season_names(s: int, kind: str) -> list[str]:
    """Kodi's names for a season's art; the first is the one muthur writes."""
    return [f"season-specials-{kind}.jpg", f"season00-{kind}.jpg"] if s == 0 else [f"season{s:02d}-{kind}.jpg", f"season{s}-{kind}.jpg"]


class Artwork:
    def __init__(self, tmdb, fanart, exists):
        """fanart: a FanartTv, or None without keys; exists(library path): whether the file is there."""
        self.tmdb, self.fanart, self.exists = tmdb, fanart, exists

    def _fan(self, kind: str, item_id) -> dict:
        if not self.fanart or not item_id:
            return {}
        try:
            return self.fanart.get(kind, item_id)
        except (requests.RequestException, ValueError):  # fanart.tv down or the key refused: TMDB's art still counts
            return {}

    @staticmethod
    def _source(details: dict, field: str | None, size: str | None, fan: dict, key: str, season: int | None = None) -> dict | None:
        found = nfo_write.best_logo(details) if field == "logo" else details.get(field) if field else None
        if found:
            return {"from": "tmdb", "src": found, "size": size}
        url = best(fan.get(key), season) if fan else None
        return {"from": "fanart.tv", "src": url} if url else None

    def show(self, folder: str, tmdb_id: int, label: str, seasons: set[int]) -> list[dict]:
        """The show's own artwork and its seasons' (the library's seasons that TMDB numbers the same way)."""
        d = self.tmdb.tv_full(tmdb_id) or {}
        fan = self._fan("tv", (d.get("external_ids") or {}).get("tvdb_id"))
        base, out = f"TV/{folder}", []
        for name, field, size, key in SHOW:
            if not self.exists(f"{base}/{name}") and (src := self._source(d, field, size, fan, key)):
                out.append({"path": f"{base}/{name}", "nfo": f"{base}/tvshow.nfo", "label": f"{label}: {WHAT[name.split('.')[0]]}", **src})
        on_tmdb = {x.get("season_number"): x for x in d.get("seasons", [])}
        for s in sorted(seasons):
            for kind, field, size, key in SEASON:
                names = season_names(s, kind)
                if any(self.exists(f"{base}/{n}") for n in names):
                    continue
                if src := self._source(on_tmdb.get(s) or {}, field, size, fan, key, s):
                    which = "specials" if s == 0 else f"season {s}"
                    out.append({"path": f"{base}/{names[0]}", "nfo": f"{base}/tvshow.nfo", "label": f"{label}: {which} {WHAT[kind]}", **src})
        return out

    def thumb(self, stem: str, tmdb_id: int, season: int, episode: int, label: str) -> dict | None:
        """An episode's thumbnail from TMDB's still: '<video name>-thumb.jpg' beside it. season, episode: TMDB's."""
        if self.exists(stem + "-thumb.jpg"):
            return None
        listed = (self.tmdb.tv_season(tmdb_id, season) or {}).get("episodes", [])
        ep = next((e for e in listed if e.get("episode_number") == episode), None)
        if not ep or not ep.get("still_path"):
            return None
        return {"path": stem + "-thumb.jpg", "nfo": stem + ".nfo", "label": f"{label}: thumbnail", "from": "tmdb",
                "src": ep["still_path"], "size": "original"}

    def film(self, prefix: str, tmdb_id: int, label: str, nfo: str, soon: set[str] | None = None) -> list[dict]:
        """prefix: 'Film/…/X (1999)-', the video's name. soon: the names Health's 'film-art' gives plain ones in the
        film's folder before this runs, which count as there."""
        d = self.tmdb.movie_full(tmdb_id) or {}
        fan = self._fan("movies", tmdb_id)
        out = []
        for name, field, size, key in FILM:
            kind = name.split(".")[0]
            if any(self.exists(prefix + kind + e) or prefix + kind + e in (soon or set()) for e in (".jpg", ".png")):
                continue
            if src := self._source(d, field, size, fan, key):
                out.append({"path": prefix + name, "nfo": nfo, "label": f"{label}: {WHAT[kind]}", **src})
        return out
