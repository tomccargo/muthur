"""Kodi NFO files from TMDB data (ARCHITECTURE.md §7).

Formats per the Kodi wiki: NFO_files/TV_shows, NFO_files/Episodes, NFO_files/Movies.
Kodi reads season and episode numbers from the file name, so the NFO only adds
the rest. IMDb scores join the ratings block in milestone 4; until then TMDB's
own score is the default rating.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from . import __version__

MAX_ACTORS = 15
PROFILE = "https://image.tmdb.org/t/p/w185"


def _add(parent, tag: str, value) -> None:
    if value not in (None, "", []):
        ET.SubElement(parent, tag).text = str(value)


def _ratings(parent, average, votes) -> None:
    if average:
        ratings = ET.SubElement(parent, "ratings")
        r = ET.SubElement(ratings, "rating", name="themoviedb", max="10", default="true")
        _add(r, "value", round(float(average), 1))
        _add(r, "votes", int(votes or 0))


def _ids(parent, tmdb_id, imdb_id=None, tvdb_id=None) -> None:
    ET.SubElement(parent, "uniqueid", type="tmdb", default="true").text = str(tmdb_id)
    if imdb_id:
        ET.SubElement(parent, "uniqueid", type="imdb").text = str(imdb_id)
    if tvdb_id:
        ET.SubElement(parent, "uniqueid", type="tvdb").text = str(tvdb_id)


def _actors(parent, cast: list[dict], role_key) -> None:
    for i, person in enumerate(cast[:MAX_ACTORS]):
        a = ET.SubElement(parent, "actor")
        _add(a, "name", person.get("name"))
        _add(a, "role", role_key(person))
        _add(a, "order", i)
        if person.get("profile_path"):
            _add(a, "thumb", PROFILE + person["profile_path"])


def _serialise(root: ET.Element, source: str) -> bytes:
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    head = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<!-- written by muthur {__version__} from {source} -->\n'
    return (head + body + "\n").encode("utf-8")


def tvshow_nfo(show: dict, title: str) -> bytes:
    """show: TMDB /tv/{id} with external_ids and aggregate_credits."""
    root = ET.Element("tvshow")
    _add(root, "title", title)
    _add(root, "originaltitle", show.get("original_name"))
    _add(root, "showtitle", title)
    first = show.get("first_air_date") or ""
    _add(root, "year", first[:4])
    _add(root, "premiered", first)
    _add(root, "plot", show.get("overview"))
    _add(root, "status", show.get("status"))
    for g in show.get("genres", []):
        _add(root, "genre", g.get("name"))
    for n in show.get("networks", [])[:2]:
        _add(root, "studio", n.get("name"))
    _ratings(root, show.get("vote_average"), show.get("vote_count"))
    ext = show.get("external_ids") or {}
    _ids(root, show["id"], ext.get("imdb_id"), ext.get("tvdb_id"))
    cast = (show.get("aggregate_credits") or {}).get("cast", [])
    _actors(root, cast, lambda p: ((p.get("roles") or [{}])[0]).get("character"))
    return _serialise(root, f"TMDB tv/{show['id']}")


def episode_nfo(show_title: str, season: int, episode: dict, show_id: int, number: int | None = None,
                title: str | None = None) -> bytes:
    """episode: one entry of TMDB /tv/{id}/season/{n} 'episodes'.
    number, title: the file's own episode number and title when the library numbers the show
    differently from TMDB (the second half of a split episode is 'Goodbye Toby (2)', S04E19)."""
    root = ET.Element("episodedetails")
    _add(root, "title", title or episode.get("name"))
    _add(root, "showtitle", show_title)
    _add(root, "season", season)
    _add(root, "episode", number if number is not None else episode.get("episode_number"))
    _add(root, "aired", episode.get("air_date"))
    _add(root, "plot", episode.get("overview"))
    _add(root, "runtime", episode.get("runtime"))
    _ratings(root, episode.get("vote_average"), episode.get("vote_count"))
    if episode.get("id"):
        ET.SubElement(root, "uniqueid", type="tmdb", default="true").text = str(episode["id"])
    for c in episode.get("crew", []):
        if c.get("job") == "Director":
            _add(root, "director", c.get("name"))
        elif c.get("department") == "Writing":
            _add(root, "credits", c.get("name"))
    return _serialise(root, f"TMDB tv/{show_id} season {season}")


def movie_nfo(movie: dict, title: str) -> bytes:
    """movie: TMDB /movie/{id} with external_ids and credits."""
    root = ET.Element("movie")
    _add(root, "title", title)
    _add(root, "originaltitle", movie.get("original_title"))
    released = movie.get("release_date") or ""
    _add(root, "year", released[:4])
    _add(root, "premiered", released)
    _add(root, "plot", movie.get("overview"))
    _add(root, "tagline", movie.get("tagline"))
    _add(root, "runtime", movie.get("runtime"))
    for g in movie.get("genres", []):
        _add(root, "genre", g.get("name"))
    for c in movie.get("production_countries", [])[:3]:
        _add(root, "country", c.get("name"))
    for s in movie.get("production_companies", [])[:3]:
        _add(root, "studio", s.get("name"))
    crew = (movie.get("credits") or {}).get("crew", [])
    for c in crew:
        if c.get("job") == "Director":
            _add(root, "director", c.get("name"))
    for c in crew:
        if c.get("department") == "Writing":
            _add(root, "credits", c.get("name"))
    if movie.get("belongs_to_collection"):
        s = ET.SubElement(root, "set")
        _add(s, "name", movie["belongs_to_collection"].get("name"))
    _ratings(root, movie.get("vote_average"), movie.get("vote_count"))
    _ids(root, movie["id"], movie.get("imdb_id") or (movie.get("external_ids") or {}).get("imdb_id"))
    _actors(root, (movie.get("credits") or {}).get("cast", []), lambda p: p.get("character"))
    return _serialise(root, f"TMDB movie/{movie['id']}")


def best_logo(details: dict) -> str | None:
    """A PNG logo in English or without language, if TMDB has one (Kodi's clearlogo)."""
    logos = (details.get("images") or {}).get("logos", [])
    pngs = [lg for lg in logos if (lg.get("file_path") or "").endswith(".png") and lg.get("iso_639_1") in ("en", None)]
    pngs.sort(key=lambda lg: (lg.get("iso_639_1") != "en", -(lg.get("vote_average") or 0)))
    return pngs[0]["file_path"] if pngs else None
