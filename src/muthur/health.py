"""Health: what is wrong in the library, and the fixes muthur can make safely (phase 3 of §12).

check() reads the library index and sorts every problem into a fix muthur can make without a
guess, or a question for the reader. apply() carries out the fixes the reader chose, journalled
like every other change: files go to quarantine, NFOs and artwork are only created where none
exist, and an existing NFO only gets its IMDb rating, with a copy of the old file kept.

Safety rules for episodes: muthur only writes or scores an episode when TMDB numbers its season
the way the library does (the season holds no number beyond TMDB's count) and the episode title
in the file name, when there is one, doesn't belong to another TMDB episode.
"""
from __future__ import annotations

import os
import time

from . import nfo_write
from .identify import identify_movie, identify_show
from .index import JUNK
from .inbox import OTHER_EPISODE, SAME_EPISODE, _bare
from .journal import fingerprint
from .media import probe_duration
from .naming import LATIN_SCRIPT, display_title
from .parse import parse_show_folder
from .scores import ScoreRefresh, with_imdb
from .text import normalize, similarity

FIXES = ("leftovers", "empty-films", "episode-nfos", "show-nfos", "film-nfos", "imdb-scores")


class Health:
    def __init__(self, store, journal, imdb, tmdb, index, tv_root: str, film_root: str, quarantine: str, backups: str):
        self.store, self.journal, self.imdb, self.tmdb, self.index = store, journal, imdb, tmdb, index
        self.roots = {"TV": tv_root, "Film": film_root}
        self.quarantine = quarantine
        self.scores = ScoreRefresh(store, journal, imdb, tmdb, tv_root, film_root, backups)

    def _full(self, path: str) -> str:
        lib, _, rel = path.partition("/")
        return os.path.join(self.roots[lib], *rel.split("/"))

    # -- finding problems --------------------------------------------------------------------
    def check(self, lib: dict, job=None) -> dict:
        fixes: dict[str, list] = {k: [] for k in FIXES}
        manual: dict[str, list] = {"shows": [], "seasons": [], "numbers": [], "films": []}
        if job:
            job.total, job.done = len(lib["shows"]) + 1, 0
        for show in lib["shows"]:
            self._show(show, fixes, manual)
            if job:
                job.done += 1
        for f in lib["films"]:
            self._film(f, fixes, manual)
        if job:
            job.done += 1
        return {"at": time.time(), "fixes": fixes, "manual": manual}

    def _show(self, show: dict, fixes: dict, manual: dict) -> None:
        folder = show["folder"]
        for f in show["loose"]:
            fixes["leftovers"].append({"path": f"TV/{folder}/{f}", "why": "junk" if JUNK.search(f) else "belongs to no video"})
        imdb_id, tmdb_id = self.scores.show_ids(folder)
        eps = show["episodes"]
        if not tmdb_id and (not show["nfo"] or any(not e["nfo"] for e in eps)):
            # Look it up on TMDB by the folder name, as for a download; only a certain match counts.
            p = parse_show_folder(folder)
            wanted = {(e["season"], n) for e in eps if e["season"] and not e["damaged"] for n in e["episodes"]}
            m = identify_show(self.tmdb, p.title, p.year, p.country, wanted)
            if m.status == "auto":
                tmdb_id, imdb_id = m.best.tmdb_id, m.best.imdb_id
            else:
                guess = f" Its best guess, {m.best.title} ({m.best.year}), isn't certain." if m.best else ""
                manual["shows"].append({"path": f"TV/{folder}", "why": f"muthur can't place this show on TMDB with certainty.{guess}"})
        if not tmdb_id:
            return
        details = self.tmdb.tv(tmdb_id) or {}
        counts = {s["season_number"]: s.get("episode_count") or 0 for s in details.get("seasons", [])}
        title = show["title"] if show["nfo"] else details.get("name") or folder
        if not show["nfo"]:
            fixes["show-nfos"].append({"path": f"TV/{folder}/tvshow.nfo", "tmdb": tmdb_id, "label": details.get("name") or folder})
        elif imdb_id and (info := self.index.nfo(self._full(f"TV/{folder}/tvshow.nfo"))) and "imdb" not in info.ratings:
            if score := self.imdb.rating(imdb_id):
                fixes["imdb-scores"].append({"path": f"TV/{folder}/tvshow.nfo", "score": list(score), "label": title})

        numbered = [e for e in eps if e["season"] is not None and e["episodes"] and not e["damaged"]]
        for e in eps:
            if e not in numbered:
                manual["numbers"].append({"path": f"TV/{folder}/{e['file']}", "why": "The episode number in the name is damaged or missing."})
        titles: dict[int, dict[int, str]] = {}

        def season(s: int) -> dict[int, str]:
            if s not in titles:
                titles[s] = {x["episode_number"]: x.get("name") for x in (self.tmdb.tv_season(tmdb_id, s) or {}).get("episodes", [])}
            return titles[s]

        highest: dict[int, int] = {}
        for e in numbered:
            highest[e["season"]] = max(highest.get(e["season"], 0), max(e["episodes"]))
        # The season's own list is fresher than the show's episode counts, which TMDB caches longer.
        differs = {s for s, top in highest.items() if top > max(counts.get(s, 0), len(season(s)))}
        for s in sorted(differs):
            manual["seasons"].append({"path": f"TV/{folder}", "season": s,
                                      "why": f"Your library numbers season {s} up to episode {highest[s]}; TMDB has {len(season(s))}. "
                                             "Episodes whose name confirms TMDB's title at their number are still fixed; the others are listed."})
        for e in numbered:
            s, n = e["season"], e["episodes"][0]
            if e["nfo"] and (e["imdb"] or len(e["episodes"]) > 1):
                continue
            named = self.store.parsed("episode", [folder, *e["file"].split("/")]).episode_title
            if s in differs and not (named and season(s).get(n) and _same_title(named, season(s)[n])):
                manual["numbers"].append({"path": f"TV/{folder}/{e['file']}",
                                          "why": f"Season {s} is numbered differently from TMDB, and the name doesn't confirm this is "
                                                 f"TMDB's S{s:02d}E{n:02d} “{season(s).get(n) or 'nothing'}”."})
                continue
            if named and season(s).get(n) and similarity(_bare(named), _bare(titles[s][n])) < OTHER_EPISODE and any(
                    similarity(_bare(named), _bare(t or "")) >= SAME_EPISODE for k, t in titles[s].items() if k != n):
                manual["numbers"].append({"path": f"TV/{folder}/{e['file']}",
                                          "why": f"Named “{named}”, but TMDB’s S{s:02d}E{n:02d} is “{titles[s][n]}”."})
                continue
            label = f"{title} S{s:02d}E{n:02d}"
            stem = f"TV/{folder}/{e['file'].rsplit('.', 1)[0]}"
            if not e["nfo"]:
                if len(e["episodes"]) > 1:
                    continue  # double-episode NFOs: not written by muthur yet
                fixes["episode-nfos"].append({"path": stem + ".nfo", "video": f"TV/{folder}/{e['file']}", "tmdb": tmdb_id,
                                              "season": s, "episode": n, "show": title, "imdbShow": imdb_id,
                                              "thumb": None if e["thumb"] else stem + "-thumb.jpg", "label": label})
            elif score := self.imdb.episode(imdb_id, s, n, counts.get(s)):
                fixes["imdb-scores"].append({"path": stem + ".nfo", "score": list(score), "label": label})

    def _film(self, f: dict, fixes: dict, manual: dict) -> None:
        if not f["file"]:
            if f["folder"]:
                fixes["empty-films"].append({"path": f"Film/{f['key']}", "label": f["title"]})
            return
        if not f["nfo"]:
            stem = f"Film/{f['file'].rsplit('.', 1)[0]}"
            fix = {"path": stem + ".nfo", "video": f"Film/{f['file']}", "art": f"Film/{f['key']}/" if f["folder"] else stem + "-"}
            chosen = (self.store.get("library.films") or {}).get(f"Film/{f['file']}")
            if chosen:  # the reader said which film it is
                fixes["film-nfos"].append({**fix, "tmdb": chosen["tmdbId"], "label": chosen["label"]})
                return
            # Look it up on TMDB by its name and length, as for a download; only a certain match counts.
            p = self.store.parsed("movie", f["file"].split("/"))
            m = identify_movie(self.tmdb, [p.title or f["key"], *p.alt_titles], p.year, probe_duration(self._full(f"Film/{f['file']}")))
            if m.status == "auto":
                fixes["film-nfos"].append({**fix, "tmdb": m.best.tmdb_id,
                                           "label": f"{m.best.title} ({m.best.year})" if m.best.year else m.best.title})
            else:
                guess = f" Its best guess, {m.best.title} ({m.best.year}), isn't certain." if m.best else ""
                manual["films"].append({"path": f"Film/{f['file']}", "why": f"No NFO, and muthur can't tell with certainty which film it is.{guess}"})
        elif not f["imdb"] and f["ids"].get("imdb") and f.get("nfoFile"):
            if score := self.imdb.rating(f["ids"]["imdb"]):
                fixes["imdb-scores"].append({"path": f"Film/{f['nfoFile']}", "score": list(score),
                                             "label": f"{f['title']}{' (' + str(f['year']) + ')' if f.get('year') else ''}"})

    # -- fixing ------------------------------------------------------------------------------
    def apply(self, plan: dict, kinds: list[str], kodi=None, job=None) -> dict:
        items = [(k, x) for k in FIXES if k in kinds for x in plan["fixes"].get(k, [])]
        if job:
            job.total, job.done = len(items), 0
        run = self.journal.start("health")
        done, failed, nfos = {k: 0 for k in kinds}, [], []
        for kind, x in items:
            try:
                getattr(self, "_" + kind.replace("-", "_"))(run, x, nfos)
                done[kind] += 1
            except (OSError, ValueError, KeyError) as e:
                failed.append({"path": x["path"], "why": getattr(e, "strerror", None) or str(e)})
            if job:
                job.done += 1
        summary = {"done": done, "failed": failed}
        self.journal.finish(run, summary)
        if kodi and nfos:
            summary["kodi"] = kodi.refresh_files([self._full(p) for p in nfos], {v: k for k, v in self.roots.items()})
        return {"run": run, **summary}

    def _quarantine(self, run: int, path: str) -> None:
        src = self._full(path)
        if not os.path.lexists(src):
            raise ValueError("it isn't there any more")
        dst = os.path.join(self.quarantine, time.strftime("%Y-%m-%d"), *path.split("/"))
        if os.path.lexists(dst):
            dst += f" ({int(time.time())})"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        size = os.path.getsize(src) if os.path.isfile(src) else None
        op = self.journal.record(run, path, "quarantine", src, dst, size, status="failed")
        os.rename(src, dst)
        self.journal.mark(op, "done")
        if size is not None:
            with self.store.lock:
                self.store.db.execute("UPDATE ops SET digest = ? WHERE id = ?", (fingerprint(dst), op))
                self.store.db.commit()

    def _write(self, run: int, path: str, data: bytes | None) -> bool:
        full = self._full(path)
        if not data or os.path.lexists(full):
            return False
        with open(full, "xb") as fh:  # never over an existing file
            fh.write(data)
        self.journal.record(run, path, "write", None, full, len(data), fingerprint(full))
        return True

    def _leftovers(self, run, x, nfos):
        self._quarantine(run, x["path"])

    def _empty_films(self, run, x, nfos):
        if any(os.path.isfile(os.path.join(d, n)) and n.lower().endswith((".mkv", ".mp4", ".avi", ".m4v"))
               for d, _, names in os.walk(self._full(x["path"])) for n in names):
            raise ValueError("a video appeared in it since the check")
        self._quarantine(run, x["path"])

    def _episode_nfos(self, run, x, nfos):
        if not os.path.isfile(self._full(x["video"])):
            raise ValueError("the video isn't there any more")
        listed = (self.tmdb.tv_season(x["tmdb"], x["season"]) or {}).get("episodes", [])
        ep = next((e for e in listed if e.get("episode_number") == x["episode"]), None)
        if not ep:
            raise ValueError("TMDB didn't return the episode")
        score = self.imdb.episode(x["imdbShow"], x["season"], x["episode"], len(listed))
        if self._write(run, x["path"], nfo_write.episode_nfo(x["show"], x["season"], ep, x["tmdb"], imdb=score)):
            nfos.append(x["path"])
        if x.get("thumb") and ep.get("still_path"):
            self._write(run, x["thumb"], self.tmdb.image(ep["still_path"], "original"))

    def _show_nfos(self, run, x, nfos):
        show = self.tmdb.tv_full(x["tmdb"])
        if not show:
            raise ValueError("TMDB didn't return the show")
        imdb_id = (show.get("external_ids") or {}).get("imdb_id")
        if self._write(run, x["path"], nfo_write.tvshow_nfo(show, show.get("name") or x["label"], self.imdb.rating(imdb_id))):
            nfos.append(x["path"])
        folder = x["path"].rsplit("/", 1)[0]
        for name, key, size in (("poster.jpg", "poster_path", "w780"), ("fanart.jpg", "backdrop_path", "w1280")):
            if show.get(key):
                self._write(run, f"{folder}/{name}", self.tmdb.image(show[key], size))
        if logo := nfo_write.best_logo(show):
            self._write(run, f"{folder}/clearlogo.png", self.tmdb.image(logo, "w500"))

    def _film_nfos(self, run, x, nfos):
        if not os.path.isfile(self._full(x["video"])):
            raise ValueError("the video isn't there any more")
        movie = self.tmdb.movie_full(x["tmdb"])
        if not movie:
            raise ValueError("TMDB didn't return the film")
        keep = set(self.store.get("titles.keepOriginal", sorted(LATIN_SCRIPT)))
        title = display_title(movie.get("title") or x["label"], movie.get("original_title"), movie.get("original_language"), keep)
        imdb_id = movie.get("imdb_id") or (movie.get("external_ids") or {}).get("imdb_id")
        if self._write(run, x["path"], nfo_write.movie_nfo(movie, title, self.imdb.rating(imdb_id))):
            nfos.append(x["path"])
        # Artwork: 'poster.jpg' in the film's own folder, '<name>-poster.jpg' next to a loose file.
        for name, key, size in (("poster.jpg", "poster_path", "w780"), ("fanart.jpg", "backdrop_path", "w1280")):
            if movie.get(key):
                self._write(run, x["art"] + name, self.tmdb.image(movie[key], size))
        if logo := nfo_write.best_logo(movie):
            self._write(run, x["art"] + "clearlogo.png", self.tmdb.image(logo, "w500"))

    def _imdb_scores(self, run, x, nfos):
        full = self._full(x["path"])
        with open(full, encoding="utf-8", errors="strict") as f:
            text = f.read()
        new = with_imdb(text, tuple(x["score"]))
        if new is not None:
            self.scores._rewrite(run, full, text, new)
            nfos.append(x["path"])


def _same_title(named: str, tmdb_title: str) -> bool:
    """The title in a file name is TMDB's: nearly the same, or one contains the other ('The Gamble' in
    'American Enthusiast: The Gamble')."""
    a, b = normalize(_bare(named)), normalize(_bare(tmdb_title))
    return similarity(a, b) >= SAME_EPISODE or (min(len(a), len(b)) >= 4 and (a in b or b in a))
