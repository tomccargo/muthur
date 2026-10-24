"""Turn file and folder names into structured guesses.

guessit does most of the work. The rules here cover what it gets wrong on real
libraries: broken renames like ``S10E-1``, fansub ``Show - 01`` numbering,
``part01`` miniseries, ``10.5`` recap episodes, extras and samples, and
release-site prefixes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from guessit import guessit

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".m2ts", ".wmv", ".mov", ".mpg", ".mpeg", ".webm", ".iso", ".divx", ".ogm"}

SITE_PREFIX = re.compile(r"(?i)^\s*(?:www\.)?[\w-]+\.(?:org|com|net|to|re|io|tv|me|cc|ws|xyz|se|li|ch)\s+-\s+")
BROKEN_EPISODE = re.compile(r"(?i)\bS-?\d{1,3}E-\d+\b|\bS-1E")
PART_NUMBER = re.compile(r"(?i)(?<![a-z])(?:part|pt)[ ._-]?(\d{1,2})(?!\d)")
FANSUB_NUMBER = re.compile(r"\s-\s(?:EP?\s?)?(\d{1,4})(?:v\d)?(?=\s|\[|\(|\.[a-z0-9]{2,4}$|$)", re.I)
DECIMAL_NUMBER = re.compile(r"\s-\s(\d{1,3})\.5(?=\s|\[|\(|$)")
SEASON_DIR = re.compile(r"(?i)^(?:season|series|staffel|seizoen|saison)[ ._-]?(\d{1,3})$|^s(\d{1,3})$")
SPECIALS_DIR = re.compile(r"(?i)^(?:specials?|season[ ._-]?0+)$")
EXTRAS_DIR = re.compile(r"(?i)^(?:extras?|featurettes?|behind[ ._-]the[ ._-]scenes|deleted[ ._-]scenes|interviews?|trailers?|bonus|shorts?|other)$")
SAMPLE = re.compile(r"(?i)(?:^|[ ._\-\[(])sample(?:[ ._\-\])]|$)")
COUNTRY_SUFFIX = re.compile(r"\s*(?:\((US|UK|AU|NZ|CA)\)|[ ._](US|UK))\s*$")
COUNTRY_CODES = {"UK": "GB"}  # TMDB uses ISO 3166 codes

# Flags that stop an item from being processed automatically.
BLOCKING = {
    "broken-episode-number",
    "implausible-episode-number",
    "no-episode-number",
    "decimal-episode",
    "looks-like-movie",
    "season-folder-mismatch",
}


@dataclass
class Parsed:
    path: str
    kind: str  # "episode" | "movie"
    title: str | None = None
    year: int | None = None
    country: str | None = None
    season: int | None = None
    episodes: list[int] = field(default_factory=list)
    absolute: int | None = None
    special: bool = False
    extra: bool = False
    sample: bool = False
    part: int | None = None
    alt_titles: list[str] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f in BLOCKING for f in self.flags)


def is_video(name: str) -> bool:
    dot = name.rfind(".")
    return dot != -1 and name[dot:].lower() in VIDEO_EXTS


def clean(name: str) -> str:
    """Strip release-site prefixes such as 'www.site.org - '."""
    return SITE_PREFIX.sub("", name)


def _quality(g: dict) -> dict:
    keys = ("source", "screen_size", "video_codec", "audio_codec", "audio_channels", "release_group", "other", "color_depth")
    q = {}
    for k in keys:
        v = g.get(k)
        if v is not None:
            q[k] = v if isinstance(v, (str, int, float)) else ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    return q


def _country(g: dict) -> str | None:
    c = g.get("country")
    return getattr(c, "alpha2", None) if c is not None else None


FOLDER_YEAR = re.compile(r"^(.*?)[\s._-]*\(?((?:19|20)\d{2})\)?$")


def parse_show_folder(name: str) -> Parsed:
    """'Foundation (2021)', 'The Office (US)', 'Alone.Australia' -> title/year/country.

    Curated folder names are simple, so a year is only taken from the end and
    nothing else is guessed: guessit would read '30 Rock' as episode 30.
    """
    country = None
    s = clean(name).strip()
    if m := COUNTRY_SUFFIX.search(s):
        code = m.group(1) or m.group(2)
        country, s = COUNTRY_CODES.get(code, code), s[: m.start()]
    year = None
    if (m := FOLDER_YEAR.match(s)) and m.group(1).strip() and int(m.group(2)) <= date.today().year + 1:
        s, year = m.group(1), int(m.group(2))
    if " " not in s:
        s = re.sub(r"[._]+", " ", s)
    return Parsed(path=name, kind="show", title=s.strip(" -"), year=year, country=country)


def parse_episode(parts: list[str]) -> Parsed:
    """parts: [show folder, (season folder,) ..., file name]."""
    fname = clean(parts[-1])
    dirs = parts[:-1]
    p = Parsed(path="/".join(parts), kind="episode")
    p.sample = bool(SAMPLE.search(fname))
    p.extra = any(EXTRAS_DIR.match(d) for d in dirs[1:])

    folder_season = None
    for d in dirs[1:]:
        m = SEASON_DIR.match(d)
        if m:
            folder_season = int(m.group(1) or m.group(2))
        elif SPECIALS_DIR.match(d):
            folder_season = 0

    g = guessit("/".join([*dirs, fname]), {"type": "episode"})
    p.title = g.get("title")
    p.year = g.get("year")
    p.country = _country(g)
    p.quality = _quality(g)

    if BROKEN_EPISODE.search(fname):
        p.flags.append("broken-episode-number")
        p.season = folder_season
        return p

    season, episode = g.get("season"), g.get("episode")
    if isinstance(season, list):
        season = season[0]
    if season is not None and season >= 1900:
        season = folder_season  # guessit read the year in 'Show (2006)' as season 2006
    episodes = episode if isinstance(episode, list) else [episode] if episode is not None else []

    if episodes and season is not None:
        p.season, p.episodes = season, episodes
    elif episodes:
        # No season anywhere: fansub or anime style absolute numbering.
        p.absolute = episodes[0]
        p.episodes = episodes
        p.season = folder_season
        p.flags.append("absolute-number")
    else:
        stem = fname.rsplit(".", 1)[0]
        if DECIMAL_NUMBER.search(stem):
            p.flags.append("decimal-episode")
            p.special = True
        elif (m := PART_NUMBER.search(stem)) and not g.get("season"):
            p.season, p.episodes = folder_season or 1, [int(m.group(1))]
            p.flags.append("part-number")
        elif m := FANSUB_NUMBER.search(stem):
            p.absolute = int(m.group(1))
            p.episodes = [p.absolute]
            p.season = folder_season
            p.flags.append("absolute-number")
        elif g.get("year") and not p.extra:
            p.flags.append("looks-like-movie")
        else:
            p.flags.append("no-episode-number")

    if p.season == 0:
        p.special = True
    if p.episodes and p.season and max(p.episodes) > 99:
        p.flags.append("implausible-episode-number")
    if folder_season is not None and p.season is not None and "absolute-number" not in p.flags and p.season != folder_season:
        p.flags.append("season-folder-mismatch")
    return p


CURATED = re.compile(r"^(?P<title>[^()\[\]]+?)\s*\((?P<year>(?:19|20)\d{2})\)")
BEFORE_YEAR = re.compile(r"^(?P<title>.+?)[\s._(\[]+(?P<year>(?:19|20)\d{2})(?=[\s._)\]]|$)")


def _curated(name: str):
    """'Back to the Future Part II (1989) [1080p]' -> ('Back to the Future Part II', 1989)."""
    m = CURATED.match(name)
    return (m.group("title").strip(" -"), int(m.group("year"))) if m else None


def _before_year(name: str):
    """Release-style 'WALL-E.2008.1080p...' -> ('WALL-E', 2008): everything before the year, dots as spaces."""
    m = BEFORE_YEAR.match(name)
    if not m:
        return None
    title = m.group("title")
    if " " not in title:
        title = re.sub(r"(?<=\w)[._](?=\w)", " ", title)
    return title.strip(" -._"), int(m.group("year"))


def parse_movie(parts: list[str]) -> Parsed:
    """parts: [movie folder, ..., file name] or [file name] for a loose file."""
    fname = clean(parts[-1])
    dirs = [clean(d) for d in parts[:-1]]
    p = Parsed(path="/".join(parts), kind="movie")
    p.sample = bool(SAMPLE.search(fname)) or any(d.lower() == "sample" for d in dirs)
    p.extra = any(EXTRAS_DIR.match(d) for d in dirs[1:])

    gf = guessit(fname, {"type": "movie"})
    gd = guessit(dirs[0], {"type": "movie"}) if dirs else {}
    # Curated folder names win when they carry a year; otherwise trust the file.
    g = gd if gd.get("year") and not gf.get("year") else gf
    if dirs and gd.get("year") and gf.get("year") and gd.get("year") != gf.get("year"):
        p.flags.append("year-conflict")
    p.title = g.get("title") or gd.get("title")
    p.year = g.get("year") or gd.get("year")
    # Curated "Title (Year)" names are exact; guessit trims words such as "Part II" or "Limited".
    stem = fname.rsplit(".", 1)[0]
    exact = (_curated(dirs[0]) if dirs else None) or _curated(stem)
    if exact:
        if p.year is not None and exact[1] != p.year and "year-conflict" not in p.flags:
            p.flags.append("year-conflict")
        if p.title and p.title != exact[0]:
            p.alt_titles.append(p.title)
        p.title, p.year = exact
    else:
        for alt in (_before_year(dirs[0]) if dirs else None, _before_year(stem)):
            if alt and alt[0] != p.title and alt[0] not in p.alt_titles:
                p.alt_titles.append(alt[0])
                p.year = p.year or alt[1]
        # guessit trimmed the title ('WALL-E' -> 'E'): the longer reading goes first.
        for alt in p.alt_titles:
            if p.title and p.title.lower() in alt.lower() and len(alt) > len(p.title):
                p.alt_titles = [p.title] + [a for a in p.alt_titles if a != alt]
                p.title = alt
                break
    p.part = gf.get("cd") or gf.get("part")
    p.quality = _quality(gf)
    if p.year is None:
        p.flags.append("no-year")
    return p
