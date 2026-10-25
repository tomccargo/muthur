"""The weekly score refresh (ARCHITECTURE.md §8): IMDb datasets in, NFOs muthur wrote updated, Kodi told.

Only NFOs muthur itself wrote are touched (found through the journal, and still carrying
muthur's comment). Each update is journalled with a copy of the old file, so a refresh can
be put back from History like any other run. NFOs from other tools wait for the library
cleanup (phase 3).
"""
from __future__ import annotations

import os
import re
import shutil

from .journal import fingerprint
from .library import scan_film
from .nfo import read_nfo

RATINGS = re.compile(r"([ \t]*)<ratings>.*?</ratings>\n?", re.S)
RATING = r'<rating name="{name}"[^>]*>\s*<value>([\d.]+)</value>\s*<votes>(\d+)</votes>'
FIRST_ID = re.compile(r"([ \t]*)<uniqueid")
MARK = "written by muthur"


def _rating(text: str, name: str) -> tuple[float, int] | None:
    m = re.search(RATING.format(name=name), text, re.S)
    return (float(m.group(1)), int(m.group(2))) if m else None


def ratings_xml(imdb: tuple[float, int] | None, tmdb: tuple[float, int] | None, indent: str = "  ") -> str:
    """The <ratings> block as nfo_write writes it: IMDb first and default, TMDB second."""
    if not imdb and not tmdb:
        return ""
    lines = [f"{indent}<ratings>"]
    for name, score in (("imdb", imdb), ("themoviedb", tmdb)):
        if score:
            default = ' default="true"' if name == "imdb" or not imdb else ""
            lines += [f'{indent}  <rating name="{name}" max="10"{default}>', f"{indent}    <value>{round(score[0], 1)}</value>",
                      f"{indent}    <votes>{int(score[1])}</votes>", f"{indent}  </rating>"]
    lines.append(f"{indent}</ratings>")
    return "\n".join(lines) + "\n"


def changed(old: tuple[float, int] | None, new: tuple[float, int] | None) -> bool:
    """Worth rewriting: a score appeared or went, moved by 0.1 or more, or its votes by 10 % or more."""
    if (old is None) != (new is None):
        return True
    if old is None or new is None:
        return False
    return round(abs(old[0] - new[0]), 2) >= 0.1 or (new[1] != old[1] and (not old[1] or abs(new[1] - old[1]) / old[1] >= 0.1))


def with_imdb(text: str, imdb: tuple[float, int] | None) -> str | None:
    """The NFO text with a new IMDb score, or None when the change isn't worth a rewrite."""
    if not changed(_rating(text, "imdb"), imdb):
        return None
    if m := RATINGS.search(text):
        # Only the IMDb entry changes; other ratings (TMDB, TVDB from Sonarr) stay, no longer the default.
        indent = m.group(1)
        block = re.sub(r'[ \t]*<rating name="imdb"[^>]*>.*?</rating>\n?', "", m.group(0), flags=re.S)
        if imdb:
            block = block.replace('default="true"', 'default="false"')
            block = re.sub(r"<ratings>\n", lambda _: "<ratings>\n" + _imdb_lines(imdb, indent + "  "), block, count=1)
        elif "<rating " not in block:
            block = ""
        elif 'default="true"' not in block:
            block = block.replace('default="false"', 'default="true"', 1)
        return text[:m.start()] + block + text[m.end():]
    if not imdb:
        return None
    if m := FIRST_ID.search(text) or CLOSE.search(text):
        indent = m.group(1) if m.re is FIRST_ID else "  "
        return text[:m.start()] + _indent(ratings_xml(imdb, None), indent) + text[m.start():]
    return None


CLOSE = re.compile(r"</(?:episodedetails|tvshow|movie)>\s*$")


def _imdb_lines(imdb: tuple[float, int], indent: str) -> str:
    return (f'{indent}<rating name="imdb" max="10" default="true">\n{indent}  <value>{round(imdb[0], 1)}</value>\n'
            f"{indent}  <votes>{int(imdb[1])}</votes>\n{indent}</rating>\n")


def _indent(block: str, indent: str) -> str:
    """ratings_xml indents by two spaces; follow the file's own indentation instead."""
    return "".join(indent + line[2:] + "\n" if line.startswith("  ") else line + "\n" for line in block.splitlines())


class ScoreRefresh:
    def __init__(self, store, journal, imdb, tmdb, tv_root: str, film_root: str, backups: str, kodi=None):
        self.store, self.journal, self.imdb, self.tmdb = store, journal, imdb, tmdb
        self.tv_root, self.film_root, self.backups, self.kodi = tv_root, film_root, backups, kodi
        self._shows: dict[str, tuple[str | None, int | None]] = {}

    def show_ids(self, folder: str) -> tuple[str | None, int | None]:
        """(IMDb ID, TMDB ID) of a show folder: from its tvshow.nfo, else through muthur's memory
        and TMDB's external IDs (NFOs from Sonarr often carry only a TVDB ID)."""
        if folder not in self._shows:
            nfo = os.path.join(self.tv_root, folder, "tvshow.nfo")
            ids = read_nfo(nfo).ids if os.path.isfile(nfo) else {}
            tmdb_id = int(ids["tmdb"]) if ids.get("tmdb", "").isdigit() else self.store.tmdb_for_folder("tv", folder)
            imdb_id = ids.get("imdb")
            if not imdb_id and tmdb_id:
                imdb_id = ((self.tmdb.tv(tmdb_id) or {}).get("external_ids") or {}).get("imdb_id")
            self._shows[folder] = (imdb_id, tmdb_id)
        return self._shows[folder]

    def library_ids(self) -> tuple[set[str], set[str]]:
        """IMDb IDs of the shows and films in the library."""
        shows, films = set(), set()
        if os.path.isdir(self.tv_root):
            for name in os.listdir(self.tv_root):
                if os.path.isdir(os.path.join(self.tv_root, name)) and not name.startswith((".", "@", "#")):
                    if i := self.show_ids(name)[0]:
                        shows.add(i)
        if os.path.isdir(self.film_root):
            for unit in scan_film(self.film_root):
                if unit.nfo and (i := read_nfo(unit.nfo).ids.get("imdb")):
                    films.add(i)
        return shows, films

    def run(self, job=None) -> dict:
        shows, films = self.library_ids()
        info = self.imdb.refresh(shows, films, job)
        paths = self.journal.written("nfo")
        if job:
            job.total, job.done = len(paths) + 2, 2
        run, updated = None, []
        for path in paths:
            if job:
                job.done += 1
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            if MARK not in text:
                continue  # replaced by hand or by another tool since: not muthur's any more
            new = with_imdb(text, self._score(path, text))
            if new is None:
                continue
            if run is None:
                run = self.journal.start("scores")
            self._rewrite(run, path, text, new)
            updated.append(path)
        summary = {"checked": len(paths), "updated": len(updated), "imdb": info}
        if run is not None:
            self.journal.finish(run, summary)
        if self.kodi and updated:
            summary["kodi"] = self.kodi.refresh_files(updated, {self.tv_root: "TV", self.film_root: "Film"})
        return summary

    def _score(self, path: str, text: str) -> tuple[float, int] | None:
        info = read_nfo(path)
        if info.kind in ("tvshow", "movie"):
            return self.imdb.rating(info.ids.get("imdb"))
        if info.kind != "episodedetails":
            return None
        show_imdb, show_tmdb = self.show_ids(os.path.relpath(path, self.tv_root).split(os.sep)[0])
        season, episode = (re.search(rf"<{t}>(\d+)</{t}>", text) for t in ("season", "episode"))
        if not (season and episode and show_imdb and show_tmdb):
            return None
        s, e = int(season.group(1)), int(episode.group(1))
        listed = (self.tmdb.tv_season(show_tmdb, s) or {}).get("episodes", [])
        at_number = next((x for x in listed if x.get("episode_number") == e), None)
        if not at_number or str(at_number.get("id")) != info.ids.get("tmdb"):
            return None  # filed under another number than TMDB's (Review): IMDb's score can't be matched safely
        return self.imdb.episode(show_imdb, s, e, len(listed))

    def _rewrite(self, run: int, path: str, old: str, new: str) -> None:
        """Keep a copy of the old NFO, replace it in one step, and journal both."""
        os.makedirs(os.path.join(self.backups, str(run)), exist_ok=True)
        backup = os.path.join(self.backups, str(run), f"{len(os.listdir(os.path.join(self.backups, str(run)))):05d}.nfo")
        shutil.copyfile(path, backup)
        tmp = path + ".muthur-tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new)
        os.replace(tmp, path)
        self.journal.record(run, os.path.basename(path), "update", backup, path, len(new.encode()), fingerprint(path))
