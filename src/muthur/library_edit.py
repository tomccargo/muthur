"""Edits from the Library page (ARCHITECTURE.md §13): change a show's or film's match, its title, its poster.

Every edit is one journalled run ('library'): a new file is a 'write', a replaced file an 'update'
with a copy of the old one, so History can put any edit back.
"""
from __future__ import annotations

import html
import os
import re

from . import nfo_write
from .naming import LATIN_SCRIPT, display_title


class LibraryEdit:
    def __init__(self, store, journal, tmdb, imdb, tv_root: str, film_root: str, backups: str):
        self.store, self.journal, self.tmdb, self.imdb = store, journal, tmdb, imdb
        self.roots, self.backups = {"TV": tv_root, "Film": film_root}, backups

    def full(self, path: str) -> str:
        lib, _, rel = path.partition("/")
        if lib not in self.roots or not rel or ".." in rel.split("/"):
            raise ValueError("Not a path in the library.")
        return os.path.join(self.roots[lib], *rel.split("/"))

    def _put(self, run: int, path: str, data: bytes | None) -> int:
        """Write a file; an existing one is kept as a backup first. Returns 1 when something was written."""
        if not data:
            return 0
        full = self.full(path)
        if os.path.isfile(full):
            self.journal.replace(run, path, full, data, self.backups)
        else:
            self.journal.mkdirs(run, path, os.path.dirname(full))
            self.journal.create(run, path, full, data)
        return 1

    def _title(self, d: dict, kind: str) -> str:
        keep = set(self.store.get("titles.keepOriginal", sorted(LATIN_SCRIPT)))
        name, orig = (d.get("name"), d.get("original_name")) if kind == "tv" else (d.get("title"), d.get("original_title"))
        return display_title(name or orig or "", orig, d.get("original_language"), keep)

    def _art(self, run: int, prefix: str, d: dict) -> int:
        """poster/fanart/clearlogo: 'Film/X/poster.jpg' with prefix 'Film/X/', 'Film/X-poster.jpg' with prefix 'Film/X-'."""
        n = 0
        for name, key, size in (("poster.jpg", "poster_path", "w780"), ("fanart.jpg", "backdrop_path", "w1280")):
            if d.get(key):
                n += self._put(run, prefix + name, self.tmdb.image(d[key], size))
        if logo := nfo_write.best_logo(d):
            n += self._put(run, prefix + "clearlogo.png", self.tmdb.image(logo, "w500"))
        return n

    # -- the edits ------------------------------------------------------------------------
    def match_show(self, folder: str, tmdb_id: int) -> dict:
        show = self.tmdb.tv_full(tmdb_id)
        if not show:
            raise ValueError("TMDB didn't return that show.")
        title = self._title(show, "tv")
        imdb_id = (show.get("external_ids") or {}).get("imdb_id")
        run = self.journal.start("library")
        n = self._put(run, f"TV/{folder}/tvshow.nfo", nfo_write.tvshow_nfo(show, title, self.imdb.rating(imdb_id)))
        n += self._art(run, f"TV/{folder}/", show)
        year = int(show["first_air_date"][:4]) if (show.get("first_air_date") or "")[:4].isdigit() else None
        self.store.remember("tv", title, tmdb_id, year, title, folder, "confirmed")
        summary = {"label": f"{title} is now the match for TV/{folder}", "changed": n}
        self.journal.finish(run, summary)
        return {"run": run, **summary, "nfo": f"TV/{folder}/tvshow.nfo"}

    def match_film(self, video: str, nfo: str | None, art_prefix: str, tmdb_id: int) -> dict:
        movie = self.tmdb.movie_full(tmdb_id)
        if not movie:
            raise ValueError("TMDB didn't return that film.")
        title = self._title(movie, "movie")
        imdb_id = movie.get("imdb_id") or (movie.get("external_ids") or {}).get("imdb_id")
        nfo = nfo or video.rsplit(".", 1)[0] + ".nfo"
        run = self.journal.start("library")
        n = self._put(run, nfo, nfo_write.movie_nfo(movie, title, self.imdb.rating(imdb_id)))
        n += self._art(run, art_prefix, movie)
        year = (movie.get("release_date") or "")[:4]
        summary = {"label": f"{title}{f' ({year})' if year else ''} is now the match for {video}", "changed": n}
        self.journal.finish(run, summary)
        return {"run": run, **summary, "nfo": nfo}

    def retitle(self, nfo: str, title: str) -> dict:
        title = title.strip()
        if not title:
            raise ValueError("Type a title.")
        full = self.full(nfo)
        with open(full, encoding="utf-8") as f:
            text = f.read()
        new, count = re.subn(r"<title>.*?</title>", lambda _: f"<title>{html.escape(title, quote=False)}</title>", text, count=1, flags=re.S)
        if not count:
            raise ValueError("That NFO has no title to change.")
        run = self.journal.start("library")
        self._put(run, nfo, new.encode("utf-8"))
        summary = {"label": f"Title set to {title}", "changed": 1}
        self.journal.finish(run, summary)
        return {"run": run, **summary, "nfo": nfo}

    def posters(self, kind: str, tmdb_id: int) -> list[dict]:
        data = self.tmdb.get(f"/{'tv' if kind == 'tv' else 'movie'}/{tmdb_id}/images", include_image_language="en,null")
        return [{"path": p["file_path"], "language": p.get("iso_639_1"), "votes": p.get("vote_count") or 0}
                for p in (data or {}).get("posters", [])[:24]]

    def set_poster(self, target: str, image_path: str) -> dict:
        if not re.fullmatch(r"/[\w-]+\.(jpg|png)", image_path):
            raise ValueError("Not a TMDB image.")
        run = self.journal.start("library")
        n = self._put(run, target, self.tmdb.image(image_path, "w780"))
        summary = {"label": f"New poster for {target.rsplit('/', 1)[0]}", "changed": n}
        self.journal.finish(run, summary)
        return {"run": run, **summary}
