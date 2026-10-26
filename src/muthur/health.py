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

from . import nfo_write, quarantine, subtitles
from . import rename as renaming
from .art import poster_problem
from .identify import identify_movie, identify_show
from .index import JUNK
from .inbox import OTHER_EPISODE, SAME_EPISODE, _bare, same_title
from .media import probe_duration
from .naming import LATIN_SCRIPT, display_title, movie_path
from .parse import is_video, parse_show_folder
from .scores import ScoreRefresh, with_imdb
from .text import similarity

# In the order they are applied: renames last, so NFOs and scores written in the same run move along with their video.
FIXES = ("imdb-data", "leftovers", "empty-films", "subtitles", "episode-nfos", "show-nfos", "film-nfos", "posters", "imdb-scores",
         "renames", "film-renames")


class Health:
    def __init__(self, store, journal, imdb, tmdb, index, tv_root: str, film_root: str, quarantine: str, backups: str):
        self.store, self.journal, self.imdb, self.tmdb, self.index = store, journal, imdb, tmdb, index
        self.roots = {"TV": tv_root, "Film": film_root}
        self.quarantine, self.backups = quarantine, backups
        self.scores =ScoreRefresh(store, journal, imdb, tmdb, tv_root, film_root, backups)
        self._have: set[str] | None = None  # shows whose IMDb episodes are in the kept data

    def _full(self, path: str) -> str:
        lib, _, rel = path.partition("/")
        return os.path.join(self.roots[lib], *rel.split("/"))

    # -- finding problems --------------------------------------------------------------------
    def check(self, lib: dict, job=None) -> dict:
        self._have = None
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
        self._subtitles_of("TV", folder, fixes)
        imdb_id, tmdb_id = self.scores.show_ids(folder)
        eps = show["episodes"]
        if not tmdb_id and (not show["nfo"] or any(not e["nfo"] for e in eps)):
            # Look it up on TMDB by the folder name, as for a download; only a certain match counts.
            p = parse_show_folder(folder)
            wanted = {(e["season"], n) for e in eps if e["season"] and not e["damaged"] for n in e["episodes"]}
            m = identify_show(self.tmdb, p.title or folder, p.year, p.country, wanted)
            if m.status == "auto" and m.best:
                tmdb_id, imdb_id = m.best.tmdb_id, m.best.imdb_id
            else:
                guess = f" Its best guess, {m.best.title} ({m.best.year}), isn't certain." if m.best else ""
                manual["shows"].append({"path": f"TV/{folder}", "why": f"muthur can't place this show on TMDB with certainty.{guess}"})
        if not tmdb_id:
            return
        details = self.tmdb.tv(tmdb_id) or {}
        counts = {s["season_number"]: s.get("episode_count") or 0 for s in details.get("seasons", [])}
        title = show["title"] if show["nfo"] else details.get("name") or folder
        if self._have is None:
            self._have = self.imdb.shows_with_data()
        if imdb_id and imdb_id not in self._have:
            # Its IMDb ID came after the last download (a new show, an NFO written since): its scores aren't there yet.
            fixes["imdb-data"].append({"path": f"TV/{folder}", "label": title})
        if show["nfo"]:  # a show without an NFO gets its poster with it ('show-nfos')
            self._poster([f"TV/{folder}/poster.jpg"], "tv", tmdb_id, f"TV/{folder}/tvshow.nfo", title, fixes)
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
            written = e["nfo"] and (e["imdb"] or len(e["episodes"]) > 1)  # nothing to write or score: only its name is checked
            named = self.store.parsed("episode", [folder, *e["file"].split("/")]).episode_title
            if s in differs and not (named and season(s).get(n) and same_title(named, season(s)[n])):
                if not written:
                    manual["numbers"].append({"path": f"TV/{folder}/{e['file']}",
                                              "why": f"Season {s} is numbered differently from TMDB, and the name doesn't confirm this is "
                                                     f"TMDB's S{s:02d}E{n:02d} “{season(s).get(n) or 'nothing'}”."})
                continue
            if named and season(s).get(n) and similarity(_bare(named), _bare(titles[s][n])) < OTHER_EPISODE and any(
                    similarity(_bare(named), _bare(t or "")) >= SAME_EPISODE for k, t in titles[s].items() if k != n):
                if not written:
                    manual["numbers"].append({"path": f"TV/{folder}/{e['file']}",
                                              "why": f"Named “{named}”, but TMDB’s S{s:02d}E{n:02d} is “{titles[s][n]}”."})
                continue
            label = f"{title} S{s:02d}E{n:02d}"
            stem = f"TV/{folder}/{e['file'].rsplit('.', 1)[0]}"
            # Its number is trusted (as for writing its NFO): the library's name, with TMDB's title.
            if len(e["episodes"]) == 1 and not e["mismatch"] and season(s).get(n):
                new = renaming.new_name(folder, e["file"], s, e["episodes"], season(s)[n])
                if new != e["file"].rsplit("/", 1)[-1]:
                    fixes["renames"].append({"path": f"TV/{folder}/{e['file']}", "to": new, "label": label, "why": new})
            if written:
                continue
            if not e["nfo"]:
                if len(e["episodes"]) > 1:
                    continue  # double-episode NFOs: not written by muthur yet
                fixes["episode-nfos"].append({"path": stem + ".nfo", "video": f"TV/{folder}/{e['file']}", "tmdb": tmdb_id,
                                              "season": s, "episode": n, "show": title, "imdbShow": imdb_id,
                                              "thumb": None if e["thumb"] else stem + "-thumb.jpg", "label": label})
            elif score := self.imdb.episode(imdb_id, s, n, counts.get(s)):
                fixes["imdb-scores"].append({"path": stem + ".nfo", "score": list(score), "label": label})

    def _subtitles_of(self, lib: str, folder: str, fixes: dict) -> None:
        moves, orphans = subtitles.plan(lib, self.roots[lib], folder)
        fixes["subtitles"] += moves
        fixes["leftovers"] += orphans

    def _poster(self, places: list[str], kind: str, tmdb_id: int, nfo: str, label: str, fixes: dict) -> None:
        """places: the names Kodi takes as this item's poster, the one muthur would write first."""
        have = next((p for p in places if os.path.isfile(self._full(p))), None)
        why = "missing" if have is None else poster_problem(self._full(have))
        if why:
            fixes["posters"].append({"path": have or places[0], "kind": kind, "tmdb": tmdb_id, "nfo": nfo, "label": label, "why": why})

    def _film(self, f: dict, fixes: dict, manual: dict) -> None:
        if f["folder"] and f["file"]:
            self._subtitles_of("Film", f["key"], fixes)
        if f["nfo"] and f["file"] and f.get("year") and f["title"] and not f["others"] and f["file"].count("/") == (1 if f["folder"] else 0):
            # 'Title (Year)/Title (Year).mkv' from its NFO. A film with extra videos, or one a folder deeper, keeps its name.
            want = movie_path(f["title"], f["year"], os.path.splitext(f["file"])[1])
            new_folder = want.split("/")[0]
            taken = new_folder != (f["key"] if f["folder"] else None) and os.path.lexists(self._full(f"Film/{new_folder}"))
            if want != f["file"] and not taken:
                fixes["film-renames"].append({"path": f"Film/{f['file']}", "to": want, "folder": f["key"] if f["folder"] else None,
                                              "label": new_folder, "why": f"from {f['file'].split('/')[0]}"})
        if f["nfo"] and f["file"] and f.get("nfoFile") and str(f["ids"].get("tmdb", "")).isdigit():
            stem = f"Film/{f['file'].rsplit('.', 1)[0]}"  # beside the video, where Kodi looks: 'poster.jpg' in its folder, else '<name>-poster.jpg'
            folder = f"Film/{f['file'].rsplit('/', 1)[0]}"
            places = ([f"{folder}/poster.jpg", f"{folder}/folder.jpg"] if f["folder"] and "/" in f["file"] else []) + [stem + "-poster.jpg"]
            self._poster(places, "movie", int(f["ids"]["tmdb"]), f"Film/{f['nfoFile']}",
                         f"{f['title']}{' (' + str(f['year']) + ')' if f.get('year') else ''}", fixes)
        if not f["file"]:
            if f["folder"]:
                fixes["empty-films"].append({"path": f"Film/{f['key']}", "label": f["title"]})
            return
        if not f["nfo"]:
            stem = f"Film/{f['file'].rsplit('.', 1)[0]}"
            fix = {"path": stem + ".nfo", "video": f"Film/{f['file']}", "art": f"Film/{f['file'].rsplit('/', 1)[0]}/" if f["folder"] else stem + "-"}  # beside the video, where Kodi looks
            chosen = (self.store.get("library.films") or {}).get(f"Film/{f['file']}")
            if chosen:  # the reader said which film it is
                fixes["film-nfos"].append({**fix, "tmdb": chosen["tmdbId"], "label": chosen["label"]})
                return
            # Look it up on TMDB by its name and length, as for a download; only a certain match counts.
            p = self.store.parsed("movie", f["file"].split("/"))
            m = identify_movie(self.tmdb, [p.title or f["key"], *p.alt_titles], p.year, probe_duration(self._full(f"Film/{f['file']}")))
            if m.status == "auto" and m.best:
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
        self._renamed: list[tuple[str, str]] = []
        self._before: dict | None = None  # Kodi's items before the renames; None: Kodi is off, so nothing is renamed
        if {"renames", "film-renames"} & set(kinds) and kodi and kodi.check().get("connected"):
            if job:
                job.begin("Reading what Kodi knows", 0)
            self._before = renaming.read_before(kodi, self.roots)
        if job:
            job.step, job.total, job.done = None, len(items), 0
        run = self.journal.start("health")
        done, failed, nfos = {k: 0 for k in kinds}, [], []  # type: ignore[var-annotated]
        for kind, x in items:
            try:
                getattr(self, "_" + kind.replace("-", "_"))(run, x, nfos)
                done[kind] += 1
            except (OSError, ValueError, KeyError) as e:
                failed.append({"path": x["path"], "why": getattr(e, "strerror", None) or str(e)})
            if job:
                job.done += 1
        summary = {"done": done, "failed": failed}
        if kodi and self._renamed and self._before is not None:
            if job:
                job.begin(f"Kodi takes {len(self._renamed):,} new names", 0)
            summary["kodiRenames"] = renaming.follow_in_kodi(kodi, self._renamed, self.roots, self._before)
        if kodi and nfos:
            if job:
                job.begin(f"Asking Kodi to re-read {len(nfos):,} changed NFOs", len(nfos))
            summary["kodi"] = kodi.refresh_files([self._full(p) for p in nfos], self.roots,
                                                 (lambda d, t: setattr(job, "done", d)) if job else None)
        self.journal.finish(run, summary)  # with what Kodi said: History shows whether it re-read them
        return {"run": run, **summary}

    def _quarantine(self, run: int, path: str, why: str) -> None:
        src = self._full(path)
        if not os.path.lexists(src):
            raise ValueError("it isn't there any more")
        dst = os.path.join(self.quarantine, time.strftime("%Y-%m-%d"), *path.split("/"))
        if os.path.lexists(dst):
            dst += f" ({int(time.time())})"
        self.journal.move(run, path, src, dst, "quarantine")
        quarantine.note(self.quarantine, dst, path, run, why)

    def _write(self, run: int, path: str, data: bytes | None) -> bool:
        return self.journal.create(run, path, self._full(path), data)  # never over an existing file

    def _imdb_data(self, run, x, nfos):
        """Done for all shows at once, by the score refresh before the other fixes (web.py)."""

    def _leftovers(self, run, x, nfos):
        self._quarantine(run, x["path"], "A leftover in the library: a download site's note or other junk." if x.get("why") == "junk"
                         else "A leftover in the library: it belonged to a video that is gone.")

    def _subtitles(self, run, x, nfos):
        """Subtitles beside their video under its name, where Kodi finds them; other languages to quarantine."""
        if not os.path.isfile(self._full(x["path"])):
            raise ValueError("the video isn't there any more")
        for src, dst in x["move"]:
            self.journal.move(run, src, self._full(src), self._full(dst), "move")
        for src in x["drop"]:
            self._quarantine(run, src, "A subtitle in a language you don't keep, or a second one in a language the video already has.")
        for d in x["dirs"]:  # subtitle folders the moves emptied
            full = self._full(d)
            if os.path.isdir(full) and not [n for n in os.listdir(full) if not n.startswith(("@", ".")) and n.lower() != "thumbs.db"]:
                self._quarantine(run, d, "A subtitle folder muthur emptied.")

    def _empty_films(self, run, x, nfos):
        if any(is_video(n) and os.path.isfile(os.path.join(d, n)) for d, _, names in os.walk(self._full(x["path"])) for n in names):
            raise ValueError("a video appeared in it since the check")
        self._quarantine(run, x["path"], "A film folder without a video in it.")

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

    def _posters(self, run, x, nfos):
        """TMDB's poster where there is none or a poor one; the old one is kept (History can put it back). Kodi re-reads the item."""
        d = (self.tmdb.tv(x["tmdb"]) if x["kind"] == "tv" else self.tmdb.movie(x["tmdb"])) or {}
        data = self.tmdb.image(d["poster_path"], "w780") if d.get("poster_path") else None
        if not data:
            raise ValueError("TMDB has no poster for it")
        full = self._full(x["path"])
        if os.path.lexists(full):
            self.journal.replace(run, x["path"], full, data, self.backups)
        else:
            self._write(run, x["path"], data)
        nfos.append(x["nfo"])

    def _renames(self, run, x, nfos):
        """The library's name for an episode, with its NFO, thumbnail and subtitles; only while Kodi answers, so its
        watched status follows (rename.py)."""
        if self._before is None:
            raise ValueError("Kodi is off: renaming now would leave the watched status behind. Turn Kodi on and apply again")
        rel = x["path"].partition("/")[2]
        if not os.path.isfile(self._full(x["path"])):
            raise ValueError("the video isn't there any more")
        new = renaming.rename(self.journal, run, self.roots["TV"], "TV", rel, f"{rel.rsplit('/', 1)[0]}/{x['to']}")
        self._renamed.append((x["path"], new))

    def _film_renames(self, run, x, nfos):
        """'Title (Year)/Title (Year).mkv': the video with its NFO, artwork and subtitles, then its folder (a loose film
        gets one); a download site's notes in it go to quarantine. Only while Kodi answers, like episodes."""
        if self._before is None:
            raise ValueError("Kodi is off: renaming now would leave the watched status behind. Turn Kodi on and apply again")
        if not os.path.isfile(self._full(x["path"])):
            raise ValueError("the video isn't there any more")
        root, rel = self.roots["Film"], x["path"].partition("/")[2]
        new_folder, new_name = x["to"].split("/")
        old = x.get("folder")
        if old and old != new_folder and os.path.lexists(os.path.join(root, new_folder)):
            raise ValueError(f"{new_folder} already exists")
        renaming.rename(self.journal, run, root, "Film", rel, f"{old}/{new_name}" if old else x["to"])
        if old:
            for n in sorted(os.listdir(os.path.join(root, old))):
                if JUNK.search(n) and os.path.isfile(os.path.join(root, old, n)):
                    self._quarantine(run, f"Film/{old}/{n}", "A leftover in the library: a download site's note or other junk.")
            if old != new_folder:
                self.journal.move(run, x["path"], os.path.join(root, old), os.path.join(root, new_folder), "move")
        self._renamed.append((x["path"], f"Film/{x['to']}"))

    def _imdb_scores(self, run, x, nfos):
        full = self._full(x["path"])
        with open(full, encoding="utf-8", errors="strict") as f:
            text = f.read()
        new = with_imdb(text, tuple(x["score"]))
        if new is not None:
            self.scores._rewrite(run, full, text, new)
            nfos.append(x["path"])

