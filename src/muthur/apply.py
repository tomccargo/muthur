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
import time

from . import nfo_write, quarantine
from .journal import Journal, fingerprint

SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup")


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
                    why += f" {len(back['skipped'])} change(s) could not be put back; see History."
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
            self._mkdirs(run, item["id"], os.path.dirname(dst))
            self._move(run, item["id"], src, dst, "move")
            count += 1
            count += self._subtitles(run, item["id"], src, dst)
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
    def _mkdirs(self, run: int, item: str, path: str) -> None:
        missing = []
        p = path
        while not os.path.isdir(p):
            missing.append(p)
            p = os.path.dirname(p)
        for d in reversed(missing):
            os.mkdir(d)
            self.journal.record(run, item, "mkdir", None, d)

    def _move(self, run: int, item: str, src: str, dst: str, op: str) -> None:
        if os.path.lexists(dst):
            raise Stop(f"{dst} already exists.")
        size = os.path.getsize(src) if os.path.isfile(src) else None
        op_id = self.journal.record(run, item, op, src, dst, size, status="failed")  # journalled before it happens
        os.rename(src, dst)  # same disk: instant, and never a copy (a cross-disk rename fails instead)
        digest = fingerprint(dst) if size is not None else None
        with self.journal.store.lock:
            self.journal.store.db.execute("UPDATE ops SET status = 'done', digest = ? WHERE id = ?", (digest, op_id))
            self.journal.store.db.commit()

    def _write(self, run: int, item: str, path: str, data: bytes | None) -> int:
        """Create a new file; an existing one is left exactly as it is."""
        if not data or os.path.lexists(path):
            return 0
        with open(path, "xb") as fh:  # 'x': fails rather than overwrite
            fh.write(data)
        self.journal.record(run, item, "write", None, path, len(data), fingerprint(path))
        return 1

    def _image(self, run: int, item: str, path: str, tmdb_path: str | None, size: str) -> int:
        if not tmdb_path or os.path.lexists(path):
            return 0
        return self._write(run, item, path, self.tmdb.image(tmdb_path, size))

    def _artwork(self, run: int, item: str, folder: str, details: dict) -> int:
        n = self._image(run, item, os.path.join(folder, "poster.jpg"), details.get("poster_path"), "w780")
        n += self._image(run, item, os.path.join(folder, "fanart.jpg"), details.get("backdrop_path"), "w1280")
        n += self._image(run, item, os.path.join(folder, "clearlogo.png"), nfo_write.best_logo(details), "w500")
        return n

    def _subtitles(self, run: int, item: str, src: str, dst: str) -> int:
        """Subtitles next to the video with the same name ('x.mkv' + 'x.en.srt') follow it."""
        folder, stem = os.path.dirname(src), os.path.splitext(os.path.basename(src))[0]
        new_stem = os.path.splitext(dst)[0]
        n = 0
        for name in sorted(os.listdir(folder)):
            if name.startswith(stem) and name.lower().endswith(SUBTITLE_EXTS):
                target = new_stem + name[len(stem):]
                if not os.path.lexists(target):
                    self._move(run, item, os.path.join(folder, name), target, "move")
                    n += 1
        return n

    def _leftovers(self, run: int, item: dict) -> int:
        path = os.path.join(self.downloads, *item["id"].split("/"))
        if not os.path.isdir(path):
            return 0
        from .parse import is_video

        for dirpath, _, names in os.walk(path):
            if any(is_video(n) for n in names):
                return 0  # something playable is still there: leave the folder for the reader
        day = time.strftime("%Y-%m-%d")
        target = os.path.join(self.quarantine, day, *item["id"].split("/"))
        if os.path.lexists(target):
            target += f" ({int(time.time())})"
        self._mkdirs(run, item["id"], os.path.dirname(target))
        self._move(run, item["id"], path, target, "quarantine")
        quarantine.note(self.quarantine, target, path, run, "What was left of the download after its video moved into the library.")
        return 1
