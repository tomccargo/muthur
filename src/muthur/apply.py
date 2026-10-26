"""Apply the inbox plan: move ready downloads into the library, write NFOs and artwork.

Safety rules (ARCHITECTURE.md §5.5):
- Every change goes through the journal first, so any run or item can be undone.
- Files are moved by renaming on the same disk; never copied and deleted.
- Nothing is ever overwritten: an existing target stops the item before any change.
- Everything that can fail without touching the disk (TMDB data, checks) happens first.
- If an item still fails halfway, its changes are undone on the spot.
"""
from __future__ import annotations

import os
import re
import time

from . import nfo_write, quarantine, subtitles
from .journal import Journal
from .text import count

SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup")
SUBS_DIR = re.compile(r"(?i)^(subs?|subtitles)$")
SUB_TAG = re.compile(r"[a-z]{2,3}(-[a-z]{2,4})?|\d{1,2}")  # en, eng, pt-br, 2
SUB_WORDS = {"forced", "sdh", "cc", "hi", "default", "full", "foreign", "english", "dutch", "nederlands", "flemish", "french",
             "german", "spanish", "italian", "portuguese", "swedish", "danish", "norwegian", "finnish", "polish", "czech",
             "hungarian", "romanian", "turkish", "greek", "russian", "japanese", "korean", "chinese", "arabic", "hebrew"}


def belongs_to(name: str, stem: str) -> bool:
    """A subtitle named after the video plus only language or subtitle tags: 'x.en.srt' and 'x.forced.English.srt'
    belong to 'x.mkv'; 'x.Part.Two.2024.en.srt' (another video's) and 'xy.srt' don't."""
    if not (name.startswith(stem) and name[len(stem):len(stem) + 1] == "."):
        return False
    tags = os.path.splitext(name)[0][len(stem) + 1:].lower()
    return all(SUB_TAG.fullmatch(t) or t in SUB_WORDS for t in tags.split(".") if t)


def _tmdb_numbers(f: dict) -> tuple[int, int]:
    """The TMDB season and episode a file's NFO describes; its own numbers unless Review mapped it."""
    if f.get("tmdb_season") is not None and f.get("tmdb_episode") is not None:
        return f["tmdb_season"], f["tmdb_episode"]
    return f["season"], f["episodes"][0]


class Stop(Exception):
    """A reason not to apply an item, as a sentence for the reader."""


class Applier:
    def __init__(self, tmdb, journal: Journal, downloads: str, tv_root: str, film_root: str, quarantine: str, imdb=None):
        """imdb: an Imdb (imdb.py) for IMDb scores in the NFOs; without it they carry TMDB's only."""
        self.tmdb, self.journal, self.imdb = tmdb, journal, imdb
        self.downloads, self.roots, self.quarantine = downloads, {"TV": tv_root, "Film": film_root}, quarantine

    # -- one run --------------------------------------------------------------------
    def apply(self, items: list[dict], job=None) -> dict:
        run = self.journal.start("apply")
        results = []
        if job:
            job.total = len(items)
        for item in items:
            try:
                written = self._item(run, item)
                results.append({"id": item["id"], "ok": True, "files": written})
            except Stop as e:
                results.append({"id": item["id"], "ok": False, "why": str(e)})
            except Exception as e:  # anything unexpected: put this item back as it was
                back = self.journal.undo(run, item["id"])
                why = f"It went wrong halfway ({type(e).__name__}: {e}); muthur put back what it had changed."
                if back["skipped"]:
                    why += f" {count(len(back['skipped']), 'change')} could not be put back; see History."
                results.append({"id": item["id"], "ok": False, "why": why})
            if job:
                job.done += 1
        summary = {"applied": sum(r["ok"] for r in results), "stopped": sum(not r["ok"] for r in results), "items": results}
        self.journal.finish(run, summary)
        return {"run": run, **summary}

    # -- one item ---------------------------------------------------------------------
    def _item(self, run: int, item: dict) -> int:
        if item["status"] != "ready":
            raise Stop("Only items marked Ready are applied.")
        files = [f for f in item["files"] if f.get("target")]
        if not files:
            raise Stop("Nothing in it has a place in the library.")
        lib = files[0]["library"]
        root = self.roots[lib]
        if not os.path.isdir(root):
            raise Stop(f"The {lib} folder isn't reachable.")

        # 1. Checks and data, before anything changes.
        moves = []
        for f in files:
            src = os.path.join(self.downloads, *f["source"].split("/"))
            dst = os.path.join(root, *f["target"].split("/"))
            if not os.path.isfile(src):
                raise Stop(f"{f['source']} isn't there any more.")
            if os.path.lexists(dst):
                raise Stop(f"{lib}/{f['target']} already exists. muthur never overwrites; resolve it in Duplicates.")
            moves.append((f, src, dst))
        if item["kind"] == "tv":
            show = self.tmdb.tv_full(item["tmdb_id"])
            seasons = {s: self.tmdb.tv_season(item["tmdb_id"], s) for s in {_tmdb_numbers(f)[0] for f, _, _ in moves}}
            if not show:
                raise Stop("TMDB didn't return the show's details. Try again later.")
        else:
            movie = self.tmdb.movie_full(item["tmdb_id"])
            if not movie:
                raise Stop("TMDB didn't return the film's details. Try again later.")

        # IMDb scores, where the datasets have one muthur can trust (§8).
        imdb = self.imdb
        if item["kind"] == "tv":
            show_imdb = (show.get("external_ids") or {}).get("imdb_id")
        else:
            movie_imdb = movie.get("imdb_id") or (movie.get("external_ids") or {}).get("imdb_id")

        # 2. Changes, each one journalled.
        count = 0
        for f, src, dst in moves:
            self._move(run, item["id"], src, dst, "move")
            count += 1
            count += self._subtitles(run, item["id"], src, dst, single=len(moves) == 1)
            stem = os.path.splitext(dst)[0]
            if item["kind"] == "tv":
                ts, te = _tmdb_numbers(f)
                ep = next((e for e in seasons[ts].get("episodes", []) if e.get("episode_number") == te), None)
                if ep:
                    # A file filed under another number than TMDB's gets no IMDb score: its numbering can't be checked.
                    same = (f["season"], f["episodes"]) == (ts, [te])
                    score = imdb.episode(show_imdb, ts, te, len(seasons[ts].get("episodes", []))) if imdb and same else None
                    nfo = nfo_write.episode_nfo(item["title"], f["season"], ep, item["tmdb_id"], number=f["episodes"][0],
                                                title=f.get("title"), imdb=score)
                    count += self._write(run, item["id"], stem + ".nfo", nfo)
                    count += self._image(run, item["id"], stem + "-thumb.jpg", ep.get("still_path"), "original")
            else:
                score = imdb.rating(movie_imdb) if imdb else None
                count += self._write(run, item["id"], stem + ".nfo", nfo_write.movie_nfo(movie, item["title"], score))

        top = os.path.join(root, files[0]["target"].split("/")[0])
        if item["kind"] == "tv":
            score = imdb.rating(show_imdb) if imdb else None
            count += self._write(run, item["id"], os.path.join(top, "tvshow.nfo"), nfo_write.tvshow_nfo(show, item["title"], score))
            count += self._artwork(run, item["id"], top, show)
            for s, data in seasons.items():
                name = "season-specials-poster.jpg" if s == 0 else f"season{s:02d}-poster.jpg"
                count += self._image(run, item["id"], os.path.join(top, name), data.get("poster_path"), "w780")
        else:
            count += self._artwork(run, item["id"], top, movie)

        # 3. What's left of the download: junk only goes to quarantine; anything with video stays.
        count += self._leftovers(run, item)
        return count

    # -- building blocks ---------------------------------------------------------------
    def _move(self, run: int, item: str, src: str, dst: str, op: str) -> None:
        if os.path.lexists(dst):
            raise Stop(f"{dst} already exists.")
        self.journal.move(run, item, src, dst, op)

    def _write(self, run: int, item: str, path: str, data: bytes | None) -> int:
        """Create a new file; an existing one is left exactly as it is."""
        return int(self.journal.create(run, item, path, data))

    def _image(self, run: int, item: str, path: str, tmdb_path: str | None, size: str) -> int:
        if not tmdb_path or os.path.lexists(path):
            return 0
        return self._write(run, item, path, self.tmdb.image(tmdb_path, size))

    def _artwork(self, run: int, item: str, folder: str, details: dict) -> int:
        n = self._image(run, item, os.path.join(folder, "poster.jpg"), details.get("poster_path"), "w780")
        n += self._image(run, item, os.path.join(folder, "fanart.jpg"), details.get("backdrop_path"), "w1280")
        n += self._image(run, item, os.path.join(folder, "clearlogo.png"), nfo_write.best_logo(details), "w500")
        return n

    def _subtitles(self, run: int, item: str, src: str, dst: str, single: bool = True) -> int:
        """Subtitles follow their video: next to it with the same name ('x.mkv' + 'x.en.srt'), or in a
        'Subs' folder of the download, as 'Subs/x/2_English.srt' or, when the download holds one video,
        'Subs/English.srt'. They get the video's new name plus their language ('… (1999).en.srt'). Only
        English and ones without a language come along, Dutch only when there is no English; one per language
        (a forced track is its own). The rest stays in the download and goes to quarantine with what is left of it."""
        folder, stem = os.path.dirname(src), os.path.splitext(os.path.basename(src))[0]
        new_stem = os.path.splitext(dst)[0]
        n, have = 0, set()
        beside = [x for x in sorted(os.listdir(folder)) if belongs_to(x, stem) and x.lower().endswith(SUBTITLE_EXTS)]
        subs_dirs: list[tuple[str, list[str]]] = []  # (folder, subtitle names) in the download's 'Subs'
        if os.path.normpath(folder) != os.path.normpath(self.downloads):  # a loose file's 'Subs' would belong to nobody
            for d in sorted(os.listdir(folder)):
                base = os.path.join(folder, d)
                if not (SUBS_DIR.match(d) and os.path.isdir(base)):
                    continue
                own = os.path.join(base, stem)
                source = own if os.path.isdir(own) else base if single else None
                if source is not None:
                    subs_dirs.append((source, [x for x in os.listdir(source)
                                               if x.lower().endswith(SUBTITLE_EXTS) and os.path.isfile(os.path.join(source, x))]))
        english = any(subtitles.kind(x[len(stem):])[:2] == ("en", False) for x in beside) or any(
            subtitles.kind(os.path.splitext(x)[0])[:2] == ("en", False) for _, names in subs_dirs for x in names)

        def wanted(name: str) -> bool:
            lang, forced, _ = subtitles.kind(name)
            if lang is not None and (lang not in subtitles.KEEP or (lang, forced) in have or (lang == "nl" and english)):
                return False
            if lang:
                have.add((lang, forced))
            return True

        for name in sorted(beside, key=lambda x: subtitles.kind(x[len(stem):])[2]):  # plain before SDH
            target = new_stem + name[len(stem):]
            if wanted(name[len(stem):]) and not os.path.lexists(target):
                self._move(run, item, os.path.join(folder, name), target, "move")
                n += 1
        for source, names in subs_dirs:
            for name in sorted(names, key=lambda x: (subtitles.kind(x)[2], x)):
                bare, ext = os.path.splitext(name)
                if not wanted(bare):
                    continue
                parts, k = subtitles.new_name(new_stem, *subtitles.kind(bare)), 2
                target = ".".join(parts) + ext.lower()
                while os.path.lexists(target):  # 'x.2.en.srt': the language stays last, where Kodi reads it
                    target, k = ".".join([parts[0], str(k), *parts[1:]]) + ext.lower(), k + 1
                self._move(run, item, os.path.join(source, name), target, "move")
                n += 1
        return n

    def _leftovers(self, run: int, item: dict) -> int:
        path = os.path.join(self.downloads, *item["id"].split("/"))
        if not os.path.isdir(path):
            return 0
        from .parse import is_video

        for _, _, names in os.walk(path):
            if any(is_video(n) for n in names):
                return 0  # something playable is still there: leave the folder for the reader
        day = time.strftime("%Y-%m-%d")
        target = os.path.join(self.quarantine, day, *item["id"].split("/"))
        if os.path.lexists(target):
            target += f" ({int(time.time())})"
        self._move(run, item["id"], path, target, "quarantine")
        quarantine.note(self.quarantine, target, path, run, "What was left of the download after its video moved into the library.")
        return 1
