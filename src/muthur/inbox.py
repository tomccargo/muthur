"""What is in the downloads folder, what each item is, and where it would go.

Read-only: this module never moves, renames or writes a media file. Applying
the plan is milestone 3.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from guessit import guessit

from .apply import SUBTITLE_EXTS
from .identify import identify_movie, identify_show
from .media import probe_duration
from .naming import LATIN_SCRIPT, display_title, episode_path, movie_path
from .parse import SAMPLE, is_video
from .store import Store

SETTLE_SECONDS = 600  # a download is only handled once nothing in it changed for 10 minutes
SEASON_DIR_NAMES = ("Season {n:02d}", "Season {n}", "S{n:02d}", "Series {n}")


@dataclass
class Planned:
    source: str  # path relative to the downloads folder
    size: int
    target: str | None = None  # path relative to TV/ or Film/
    library: str | None = None  # 'TV' | 'Film'
    writes: list[str] = field(default_factory=list)
    season: int | None = None
    episodes: list[int] = field(default_factory=list)


@dataclass
class Item:
    id: str  # top-level name inside the downloads folder
    status: str  # ready | review | ignored | waiting | suspicious | packed | error
    reason: str  # a sentence for the reader
    kind: str | None = None  # 'tv' | 'movie'
    title: str | None = None
    year: int | None = None
    tmdb_id: int | None = None
    known: bool = False  # matched through the ID memory
    files: list[Planned] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    size: int = 0


def _walk(base: str, entry: str) -> list[tuple[list[str], int, float]]:
    path = os.path.join(base, entry)
    if os.path.isfile(path):
        st = os.stat(path)
        return [([entry], st.st_size, st.st_mtime)]
    out = []
    for dirpath, _, names in os.walk(path):
        rel = os.path.relpath(dirpath, base).split(os.sep)
        for n in names:
            st = os.stat(os.path.join(dirpath, n))
            out.append(([*rel, n], st.st_size, st.st_mtime))
    return out


_PART_OF_A_RELEASE = re.compile(r"(?i)^(season[ ._-]?\d+|s\d{1,2}|specials?|extras?|featurettes?|samples?|subs?|subtitles|screens?|proof|covers?|artwork)$")


_RELEASE_MARKERS = ("season", "episode", "year", "screen_size", "source", "video_codec", "release_group")

ARCHIVE = re.compile(r"(?i)\.(rar|zip|7z|r\d\d|part\d+\.rar)$")

# Programs that sometimes travel under episode or film names. They are never media.
EXECUTABLE = re.compile(r"(?i)\.(exe|scr|com|pif|bat|cmd|vbs|vbe|js|jse|wsf|msi|ps1|lnk|hta|jar|apk)$")


def _is_category(path: str) -> bool:
    """A folder of downloads ('tv-sonarr', 'movies') rather than one download: its own name
    carries no release markers, it holds two or more entries, and none of its subfolders is
    the kind a single release has (Season 1, Sample, Subs)."""
    name = os.path.basename(path.rstrip("/\\"))
    g = guessit(name, {"type": "episode"})
    if any(g.get(k) is not None for k in _RELEASE_MARKERS):
        return False
    children = [c for c in os.listdir(path) if not c.startswith((".", "@", "#"))]
    if len(children) < 2:
        return False
    return not any(_PART_OF_A_RELEASE.match(c) for c in children if os.path.isdir(os.path.join(path, c)))


def _looks_like_media(name: str) -> bool:
    g = guessit(name, {"type": "episode"})
    return any(g.get(k) is not None for k in ("season", "episode", "screen_size", "source"))


def _candidates(match) -> list[dict]:
    return [{"tmdbId": c.tmdb_id, "title": c.title, "originalTitle": c.original_title, "year": c.year,
             "score": round(c.score, 2), "signals": {k: round(v, 2) for k, v in c.signals.items() if v is not None}}
            for c in match.candidates[:3]]


def _season_dir(tv_root: str | None, folder: str | None, season: int) -> str | None:
    """The name an existing library folder already uses for this season, if any."""
    if not (tv_root and folder):
        return None
    base = os.path.join(tv_root, folder)
    for pattern in SEASON_DIR_NAMES if season else ("Specials", "Season 00", "Season 0"):
        name = pattern.format(n=season)
        if os.path.isdir(os.path.join(base, name)):
            return name
    return None


class Inbox:
    def __init__(self, tmdb, store: Store, downloads: str, tv_root: str | None = None, film_root: str | None = None):
        self.tmdb, self.store = tmdb, store
        self.downloads, self.tv_root, self.film_root = downloads, tv_root, film_root

    def keep_original(self) -> set[str]:
        return set(self.store.get("titles.keepOriginal", sorted(LATIN_SCRIPT)))

    def entries(self) -> list[str]:
        """Top-level downloads; a category folder (Download Station or Sonarr style, e.g. 'tv-sonarr/')
        is opened up so each download inside it is its own item."""
        out = []
        for e in sorted(os.listdir(self.downloads)):
            if e.startswith((".", "@", "#")):
                continue
            path = os.path.join(self.downloads, e)
            if os.path.isdir(path) and _is_category(path):
                children = sorted(c for c in os.listdir(path) if not c.startswith((".", "@", "#")))
                stems = [os.path.splitext(c)[0] for c in children if is_video(c)]
                # A loose subtitle belongs to the video it is named after; it moves with that video.
                out += [f"{e}/{c}" for c in children
                        if not (c.lower().endswith(SUBTITLE_EXTS) and any(c.startswith(st) for st in stems))]
            else:
                out.append(e)
        return out

    def scan(self, job=None) -> list[Item]:
        entries = self.entries()
        if job:
            job.total = len(entries)
        items = []
        for entry in entries:
            try:
                items.append(self.examine(entry))
            except OSError as e:
                items.append(Item(entry, "error", f"Couldn't read it: {e.strerror or e}"))
            except Exception as e:  # one odd name must not stop the whole check
                items.append(Item(entry, "error", f"muthur couldn't make sense of it ({type(e).__name__}). It stays where it is."))
            if job:
                job.done += 1
        return items

    def examine(self, entry: str) -> Item:
        files = _walk(self.downloads, entry)
        item = Item(entry, "ignored", "", size=sum(s for _, s, _ in files))
        if files and time.time() - max(m for _, _, m in files) < SETTLE_SECONDS:
            item.status, item.reason = "waiting", "Still changing; muthur looks again once it has been quiet for 10 minutes."
            return item
        disguised = [p for p, _, _ in files if EXECUTABLE.search(p[-1]) and _looks_like_media(p[-1])]
        if disguised:
            item.status = "suspicious"
            item.reason = ("A program named like an episode or film. Don't open it: this is a common way malware spreads. "
                           "muthur leaves it alone; delete it yourself.")
            item.files = [Planned("/".join(p), s) for p, s, _ in files if p in disguised]
            return item
        images = [p for p, _, _ in files if p[-1].lower().endswith(".iso") and self.store.parsed("episode", p).episodes]
        if images:
            item.status = "suspicious"
            item.reason = ("A disc image named like a TV episode. Episodes are never released as disc images, "
                           "so it may hide something else. Don't open it; delete it yourself.")
            item.files = [Planned("/".join(p), s) for p, s, _ in files if p in images]
            return item
        programs = [p for p, _, _ in files if EXECUTABLE.search(p[-1])]
        if programs:
            item.notes.append(f"Contains {len(programs)} program file(s) ({', '.join(p[-1] for p in programs[:2])}). "
                              "They are never copied into the library.")
        videos = [(p, s) for p, s, _ in files if is_video(p[-1]) and not p[-1].lower().endswith(".iso")]
        main = [(p, s) for p, s in videos if not SAMPLE.search(p[-1]) and not any(x.lower() == "sample" for x in p[:-1])]
        if not videos:
            if any(ARCHIVE.search(p[-1]) for p, _, _ in files) and any(_looks_like_media(p[-1]) for p, _, _ in files):
                item.status = "packed"
                item.reason = ("Packed in an archive. muthur doesn't unpack archives. If it opens without a password, "
                               "unpack it here and check again; one that asks for a password is a known scam.")
                return item
            item.reason = "Not video. It stays exactly where it is."
            return item
        if not main:
            item.reason = "Only a sample clip. It stays where it is."
            return item

        eps = [(self.store.parsed("episode", p), p, s) for p, s in main]
        if any(e.episodes or e.absolute for e, _, _ in eps) and not all("looks-like-movie" in e.flags for e, _, _ in eps):
            return self._tv(item, [x for x in eps if not x[0].extra])
        return self._movie(item, max(main, key=lambda x: x[1]))

    # -- TV -----------------------------------------------------------------
    def _tv(self, item: Item, eps) -> Item:
        item.kind = "tv"
        first = eps[0][0]
        title, year, country = first.title or item.id, first.year, first.country
        broken = [e for e, _, _ in eps if e.blocked]
        wanted = {(e.season, n) for e, _, _ in eps if not e.blocked and e.season for n in e.episodes}

        remembered = self.store.lookup("tv", title, year)
        folder = None
        if len(remembered) == 1:
            r = remembered[0]
            item.tmdb_id, item.known, folder = r["tmdb_id"], True, r["folder"]
            details = self.tmdb.tv(item.tmdb_id) or {}
            seasons = {s["season_number"]: s.get("episode_count") or 0 for s in details.get("seasons", [])}
            missing = [(s, n) for s, n in wanted if n > seasons.get(s, 0)]
            item.status = "review" if missing else "ready"
            item.reason = (f"{len(missing)} episode(s) don't exist on this show." if missing
                           else "A show already in the library.")
            name, orig, lang, show_year = details.get("name", r["title"]), details.get("original_name"), details.get("original_language"), r["year"]
        else:
            m = identify_show(self.tmdb, title, year, country, wanted)
            item.candidates = _candidates(m)
            if m.best is None:
                item.status, item.reason = "review", "No show by that name on TMDB. Search for it by hand."
                return item
            item.tmdb_id = m.best.tmdb_id
            item.status = "ready" if m.status == "auto" else "review"
            item.reason = "New show, matched with confidence." if m.status == "auto" else _why(m.reasons)
            if len(remembered) > 1:
                item.status, item.reason = "review", "More than one remembered show has this name."
            name, orig, lang, show_year = m.best.title, m.best.original_title, m.best.language, m.best.year
        if broken:
            item.status = "review"
            item.notes.append(f"{len(broken)} file(s) have a damaged or missing episode number.")

        shown = display_title(name, orig, lang, self.keep_original())
        item.title, item.year = shown, show_year
        titles = self._episode_titles(item.tmdb_id, {s for s, _ in wanted})
        new_show = not folder
        for e, parts, size in eps:
            p = Planned("/".join(parts), size, library="TV")
            if not e.blocked and e.season is not None and e.episodes:
                ext = os.path.splitext(parts[-1])[1]
                ep_title = titles.get((e.season, e.episodes[0]))
                if folder:
                    # An existing show keeps its folder; names inside start with that folder's name.
                    path = episode_path(folder, None, e.season, e.episodes, ep_title, ext)
                    season_dir = _season_dir(self.tv_root, folder, e.season)
                    if season_dir:
                        path = f"{folder}/{season_dir}/{path.rsplit('/', 1)[1]}"
                else:
                    path = episode_path(shown, show_year, e.season, e.episodes, ep_title, ext)
                p.target, p.season, p.episodes = path, e.season, list(e.episodes)
                stem = os.path.splitext(path.rsplit("/", 1)[1])[0]
                p.writes = [f"{stem}.nfo", f"{stem}-thumb.jpg"]
            item.files.append(p)
        if new_show and item.files and item.files[0].target:
            show_dir = item.files[0].target.split("/", 1)[0]
            item.files[0].writes = ["tvshow.nfo", "poster.jpg", "fanart.jpg", "clearlogo.png"] + item.files[0].writes
            item.notes.append(f"New show: TV/{show_dir}/ will be created.")
        return item

    def _episode_titles(self, tmdb_id: int | None, seasons: set[int]) -> dict:
        titles = {}
        for s in seasons:
            for ep in (self.tmdb.tv_season(tmdb_id, s) or {}).get("episodes", []) if tmdb_id else []:
                if ep.get("name") and not ep["name"].lower().startswith("episode "):
                    titles[(s, ep["episode_number"])] = ep["name"]
        return titles

    # -- Movies -------------------------------------------------------------
    def _movie(self, item: Item, main) -> Item:
        parts, size = main
        item.kind = "movie"
        p = self.store.parsed("movie", parts)
        duration = probe_duration(os.path.join(self.downloads, *parts))
        m = identify_movie(self.tmdb, [p.title or item.id, *p.alt_titles], p.year, duration)
        item.candidates = _candidates(m)
        planned = Planned("/".join(parts), size, library="Film")
        item.files.append(planned)
        if m.best is None:
            item.status, item.reason = "review", "No film by that name on TMDB. Search for it by hand."
            return item
        b = m.best
        shown = display_title(b.title, b.original_title, b.language, self.keep_original())
        item.tmdb_id, item.title, item.year = b.tmdb_id, shown, b.year
        item.status = "ready" if m.status == "auto" else "review"
        item.reason = "Matched with confidence." if m.status == "auto" else _why(m.reasons)
        planned.target = movie_path(shown, b.year, os.path.splitext(parts[-1])[1], p.part)
        stem = os.path.splitext(planned.target.rsplit("/", 1)[1])[0]
        planned.writes = [f"{stem}.nfo", "poster.jpg", "fanart.jpg", "clearlogo.png"]
        return item


_REASONS = {
    "title clash without a year": "Two titles share this name and the name has no year.",
    "runner-up too close": "Another candidate is almost as likely.",
    "title not an exact match": "The name only roughly matches the title on TMDB.",
    "episodes missing on the best match": "Some episode numbers don't exist on the best match.",
    "best score": "The match isn't certain enough.",
    "no candidates on TMDB": "Nothing on TMDB matches this name.",
}


def _why(reasons: list[str]) -> str:
    """The first identifier reason as a sentence (DESIGN.md §1.7: no code words on screen)."""
    for r in reasons:
        for key, sentence in _REASONS.items():
            if r.startswith(key):
                return sentence
    return "The match isn't certain enough."
