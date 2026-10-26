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
import re
import time
from collections import Counter

from . import kodi_entries, nfo_write, quarantine, subfit, subtitles
from . import rename as renaming
from .art import poster_problem
from .identify import identify_movie, identify_show
from .index import JUNK
from .inbox import OTHER_EPISODE, SAME_EPISODE, _bare, same_title
from .media import probe_duration
from .naming import LATIN_SCRIPT, display_title, movie_path
from .nfo import read_nfo
from .parse import EXTRAS_DIR, is_video, parse_show_folder
from .scores import ScoreRefresh, with_imdb
from .text import best_similarity, normalize, similarity

# In the order they are applied: renames last, so NFOs and scores written in the same run move along with their video.
FIXES = ("imdb-data", "show-rematch", "leftovers", "empty-films", "extras", "subtitles", "subtitle-timing", "subtitle-misfit", "episode-nfos", "show-nfos", "film-nfos", "posters", "imdb-scores",
         "renames", "film-renames", "kodi-entries")
TWIN = "release notes beside the NFO"  # 'x.NFO' beside 'x.nfo' (index._twin)
OLD_ART = re.compile(r"(?i)^(season(\d+|-all|-specials)-(poster|banner|fanart|landscape)|banner|landscape|clearart|logo|characterart)\.(jpg|png)$")
SPECIAL_NAME = re.compile(r"(?i)\bspecial\b")
GENERIC_TITLE = re.compile(r"(?i)^(episode|ep|part|chapter|aflevering|deel|afl)\.?\s*\d+$")  # says nothing about the show


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
    def check(self, lib: dict, job=None, kodi_items: list[dict] | None = None, prefixes: dict | None = None) -> dict:
        """kodi_items, prefixes: Kodi's films and episodes (Watched.read_kodi) and its source per library, when Kodi
        answered; then Kodi's old entries are checked too."""
        self._have = None
        # Which folders each TMDB show is in: a folder found to be another show sends the old show's episodes to its own.
        self._shows_of: dict[str, list[dict]] = {}
        for sh in lib["shows"]:
            if sh["ids"].get("tmdb"):
                self._shows_of.setdefault(str(sh["ids"]["tmdb"]), []).append(sh)
        fixes: dict[str, list] = {k: [] for k in FIXES}
        manual: dict[str, list] = {"shows": [], "seasons": [], "numbers": [], "films": []}
        if job:
            job.begin("Checking each show and film", len(lib["shows"]) + 1)
        for show in lib["shows"]:
            self._show(show, fixes, manual)
            if job:
                job.done += 1
        for f in lib["films"]:
            self._film(f, fixes, manual)
        if kodi_items is not None and prefixes:
            fixes["kodi-entries"] = kodi_entries.extra(kodi_items, self.roots, prefixes)
        if job:
            job.done += 1
        return {"at": time.time(), "fixes": fixes, "manual": manual}

    def _show(self, show: dict, fixes: dict, manual: dict) -> None:
        folder = show["folder"]
        for f in show["loose"]:
            why = "junk" if JUNK.search(f) else TWIN if f.lower().endswith(".nfo") and not f.endswith(".nfo") else "belongs to no video"
            fixes["leftovers"].append({"path": f"TV/{folder}/{f}", "why": why})
        self._subtitles_of("TV", folder, fixes)
        imdb_id, tmdb_id = self.scores.show_ids(folder)
        eps = [e for e in show["episodes"] if not e.get("extra")]  # interviews, openings...: not episodes, not questions
        for e in show["episodes"]:  # extras outside an extras folder go to the show's Extras folder (decided 26 Oct)
            if e.get("extra") and not any(EXTRAS_DIR.match(d) for d in e["file"].split("/")[:-1]):
                name = e["file"].rsplit("/", 1)[-1]
                fixes["extras"].append({"path": f"TV/{folder}/{e['file']}", "to": f"Extras/{name}", "label": f"{folder}: {name}"})
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
        if self.show_order(folder) is None and (rematch := self._rematch(folder, eps, tmdb_id)):
            fixes["show-rematch"].append(rematch)
            return  # everything else about this folder would be judged against the wrong show
        details = self.tmdb.tv(tmdb_id) or {}
        counts = {s["season_number"]: s.get("episode_count") or 0 for s in details.get("seasons", [])}
        title = show["title"] if show["nfo"] else details.get("name") or folder
        if self._have is None:
            self._have = self.imdb.shows_with_data()
        if imdb_id and imdb_id not in self._have and imdb_id not in set(self.imdb.asked()):
            # Its IMDb ID came after the last download (a new show, an NFO written since): its scores aren't there yet.
            fixes["imdb-data"].append({"path": f"TV/{folder}", "label": title})
        if show["nfo"]:  # a show without an NFO gets its poster with it ('show-nfos')
            self._poster([f"TV/{folder}/poster.jpg"], "tv", tmdb_id, f"TV/{folder}/tvshow.nfo", title, fixes)
        if not show["nfo"]:
            fixes["show-nfos"].append({"path": f"TV/{folder}/tvshow.nfo", "tmdb": tmdb_id, "label": details.get("name") or folder})
        elif imdb_id and (info := self.index.nfo(self._full(f"TV/{folder}/tvshow.nfo"))) and "imdb" not in info.ratings:
            if score := self.imdb.rating(imdb_id):
                fixes["imdb-scores"].append({"path": f"TV/{folder}/tvshow.nfo", "score": list(score), "label": title})

        # A number beyond every episode the show has, in any order (aired, DVD, absolute), is a damaged name: 'S01E968'
        # in a show of three is asked as 'which episode is this?', not taken as the season's length.
        if total := sum(counts.values()):
            eps = [{**e, "damaged": True} if e["episodes"] and max(e["episodes"]) > total else e for e in eps]
        regular = sorted(s for s in counts if s > 0)
        if len(regular) == 1:  # one season at TMDB: 'Death note - EP 1' without a season is that season's
            eps = [{**e, "season": regular[0]} if e["season"] is None and e["episodes"] and not e["damaged"] else e for e in eps]
        numbered = [e for e in eps if e["season"] is not None and e["episodes"] and not e["damaged"]]
        ask = {"tmdb": tmdb_id, "show": title}  # a question about an episode names its show, so it can be answered there
        trusted = set(self.store.get("health.trusted") or [])  # "the number is right": the reader's word over muthur's doubt
        titles: dict[int, dict[int, str | None]] = {}
        mapped = self.show_order(folder)  # another TMDB order the reader chose: the library is read by it

        def season(s: int) -> dict[int, str | None]:
            if s not in titles:
                titles[s] = ({e: x.get("name") for (ss, e), x in mapped.items() if ss == s} if mapped is not None else
                             {x["episode_number"]: x.get("name") for x in (self.tmdb.tv_season(tmdb_id, s) or {}).get("episodes", [])})
            return titles[s]

        # Episodes muthur places itself, where certain (26 Oct): file -> (TMDB season, episode, title). Not when the reader
        # chose another order (that order decides).
        self._sized: set[int] = set()  # library seasons the seasons' sizes explain (_place)
        placed = {} if mapped is not None else self._place(folder, eps, numbered, counts, season)
        for e in eps:
            if e in numbered or e["file"] in placed:
                continue
            manual["numbers"].append({"path": f"TV/{folder}/{e['file']}", **ask, "noNumber": True,
                                      "why": "The episode number in the name is damaged or missing."})
        for e in eps:  # unnumbered, but its title is one TMDB episode's: an NFO, then the library's name
            if e in numbered or e["file"] not in placed:
                continue
            s, n, t = placed[e["file"]]
            stem = f"TV/{folder}/{e['file'].rsplit('.', 1)[0]}"
            if not e["nfo"]:
                fixes["episode-nfos"].append({"path": stem + ".nfo", "video": f"TV/{folder}/{e['file']}", "tmdb": tmdb_id, "season": s,
                                              "episode": n, "show": title, "imdbShow": imdb_id, "thumb": None if e["thumb"] else stem + "-thumb.jpg",
                                              "label": f"{title} S{s:02d}E{n:02d}"})
            new = renaming.new_name(folder, e["file"], s, [n], t)
            fixes["renames"].append({"path": f"TV/{folder}/{e['file']}", "to": new, "label": f"{title} S{s:02d}E{n:02d}",
                                     "why": f"{new} (its title is TMDB's S{s:02d}E{n:02d})"})

        def aired(s: int, n: int) -> tuple[int, int]:
            """TMDB's own numbers for the library's S/E: the same, unless another order was chosen (IMDb uses these too)."""
            ep = (mapped or {}).get((s, n))
            return (int(ep["season_number"]), int(ep["episode_number"])) if ep else (s, n)

        highest: dict[int, int] = {}
        for e in numbered:
            highest[e["season"]] = max(highest.get(e["season"], 0), max(e["episodes"]))
        # The season's own list is fresher than the show's episode counts, which TMDB caches longer.
        differs = {s for s, top in highest.items() if top > (len(season(s)) if mapped is not None else max(counts.get(s, 0), len(season(s))))}
        for s in sorted(differs):
            if s in self._sized or all(e["file"] in placed for e in numbered if e["season"] == s and max(e["episodes"]) > len(season(s))):
                continue  # muthur placed every episode beyond TMDB's count itself, or the specials beyond it are asked alone
            manual["seasons"].append({"path": f"TV/{folder}", "season": s, **ask,
                                      "why": f"Your library numbers season {s} up to episode {highest[s]}; TMDB has {len(season(s))}. "
                                             "Episodes whose name confirms TMDB's title at their number are still fixed; the others are listed."})
        for e in numbered:
            if e["file"] in placed:  # another number at TMDB, certain by its title or by the seasons' sizes
                ps, pn, pt = placed[e["file"]]
                stem = f"TV/{folder}/{e['file'].rsplit('.', 1)[0]}"
                label = f"{title} S{ps:02d}E{pn:02d}"
                # Its NFO, when there is one, still says the old number: it is written again (the old one kept), so Kodi
                # doesn't show it under the number it had. Once it says TMDB's number, only the rename is left.
                info = self.index.nfo(self._full(stem + ".nfo")) if e["nfo"] else None
                if not (info and (info.season, info.episode) == (ps, pn)):
                    fixes["episode-nfos"].append({"path": stem + ".nfo", "video": f"TV/{folder}/{e['file']}", "tmdb": tmdb_id,
                                                  "season": ps, "episode": pn, "show": title, "imdbShow": imdb_id,
                                                  "thumb": None if e["thumb"] else stem + "-thumb.jpg", "label": label,
                                                  **({"replace": True} if e["nfo"] else {})})
                new = renaming.new_name(folder, e["file"], ps, [pn], pt)
                if new != e["file"].rsplit("/", 1)[-1]:
                    fixes["renames"].append({"path": f"TV/{folder}/{e['file']}", "to": new, "label": label,
                                             "why": f"{new} (TMDB's S{ps:02d}E{pn:02d}; the library had S{e['season']:02d}E{e['episodes'][0]:02d})"})
                continue
            s, n = e["season"], e["episodes"][0]
            written = e["nfo"] and (e["imdb"] or len(e["episodes"]) > 1)  # nothing to write or score: only its name is checked
            named = self.store.parsed("episode", [folder, *e["file"].split("/")]).episode_title
            sure = f"TV/{folder}/{e['file']}" in trusted
            if not sure and s in differs and s not in self._sized and not (named and season(s).get(n) and same_title(named, season(s)[n] or "")):
                if not written:
                    manual["numbers"].append({"path": f"TV/{folder}/{e['file']}", **ask,
                                              "why": f"Season {s} is numbered differently from TMDB, and the name doesn't confirm this is "
                                                     f"TMDB's S{s:02d}E{n:02d} “{season(s).get(n) or 'nothing'}”."})
                continue
            if not sure and named and season(s).get(n) and similarity(_bare(named), _bare(titles[s][n])) < OTHER_EPISODE and any(
                    similarity(_bare(named), _bare(t or "")) >= SAME_EPISODE for k, t in titles[s].items() if k != n):
                if not written:
                    manual["numbers"].append({"path": f"TV/{folder}/{e['file']}", **ask,
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
                if n not in season(s):
                    manual["numbers"].append({"path": f"TV/{folder}/{e['file']}", **ask,
                                              "why": f"TMDB has no S{s:02d}E{n:02d} for this show, so muthur can’t write its NFO."})
                    continue
                fixes["episode-nfos"].append({"path": stem + ".nfo", "video": f"TV/{folder}/{e['file']}", "tmdb": tmdb_id,
                                              "season": s, "episode": n, "show": title, "imdbShow": imdb_id,
                                              **({"aired": list(aired(s, n))} if mapped is not None else {}),
                                              "thumb": None if e["thumb"] else stem + "-thumb.jpg", "label": label})
            elif score := self.imdb.episode(imdb_id, *aired(s, n), counts.get(aired(s, n)[0])):
                fixes["imdb-scores"].append({"path": stem + ".nfo", "score": list(score), "label": label})

    def _place(self, folder: str, eps: list[dict], numbered: list[dict], counts: dict[int, int], season) -> dict[str, tuple[int, int, str]]:
        """Episodes whose TMDB number muthur can be certain of although the library's differs or is missing (26 Oct):
        file -> (season, episode, TMDB's title). Only what needs another number than the library's is returned.

        1. By title: the title in its name is one TMDB episode's title only, anywhere in the show, specials too ("Blackadder
           Rides Again" is S00E17; Fate Zero's "1x14 False Start" is S02E01). Per library season all or nothing: when two
           files claim one TMDB episode (The Office's "Fun Run (1)" and "(2)"), none of that season is placed, or Kodi
           would get two files with one number.
        2. By the seasons' sizes: a library season numbered 1..N where N is exactly its TMDB season plus the next ones,
           which the library doesn't have (Fate Zero: 25 = 13 + 12), and no title in a name says otherwise."""
        everything: list[tuple[int, int, str]] = [(s, n, t or "") for s in sorted(counts) for n, t in season(s).items() if t]
        out: dict[str, tuple[int, int, str]] = {}
        held = {(e["season"], n): e["file"] for e in numbered for n in e["episodes"]}  # numbers files have already

        def by_title(named: str | None) -> tuple[int, int, str] | None:
            if not named or len(_bare(named)) < 4:
                return None
            hits = [x for x in everything if similarity(_bare(named), _bare(x[2])) >= SAME_EPISODE]
            return hits[0] if len(hits) == 1 else None

        # 1. by title, per library season (unnumbered files form one group of their own)
        groups: dict[int | None, list[dict]] = {}
        for e in eps:
            if e["damaged"] or (e in numbered and e["season"] in counts and e["episodes"][0] in season(e["season"])
                                and same_title(self.store.parsed("episode", [folder, *e["file"].split("/")]).episode_title or "",
                                               season(e["season"])[e["episodes"][0]] or "")):
                continue  # a damaged name, or already right where TMDB has it
            groups.setdefault(e["season"] if e in numbered else None, []).append(e)
        for s, group in groups.items():
            found = {}
            for e in group:
                p = self.store.parsed("episode", [folder, *e["file"].split("/")])
                hit = by_title(p.episode_title if e in numbered else (p.episode_title or p.title or os.path.splitext(e["file"].rsplit("/", 1)[-1])[0]))
                if hit:
                    found[e["file"]] = hit
            claimed = [h[:2] for h in found.values()]
            if s is not None and len(set(claimed)) < len(claimed):
                continue  # two files, one TMDB episode: not certain for this season
            keep = {f: hit for f, hit in found.items() if not (s is None and claimed.count(hit[:2]) > 1)}
            # A number another file holds is free only when that file moves too, in the same run: a season shifted by one
            # (The Office) is renumbered as a whole, never leaving two files with one number. Repeated until nothing changes.
            changed = True
            while changed:
                changed = False
                for f, hit in list(keep.items()):
                    owner = held.get(hit[:2])
                    if owner and owner != f and owner not in keep:
                        del keep[f]
                        changed = True
            for f, hit in keep.items():
                e = next(x for x in group if x["file"] == f)
                if e in numbered and (e["season"], e["episodes"][0]) == hit[:2]:
                    continue
                out[f] = hit
        # 2. by the seasons' sizes
        for s in sorted({e["season"] for e in numbered}):
            mine = sorted(n for e in numbered if e["season"] == s for n in e["episodes"])
            if not mine or s not in counts or mine != list(range(1, len(mine) + 1)) or len(mine) <= counts[s]:
                continue
            total, chain = 0, []
            for t in range(s, max(counts) + 1):
                if t not in counts or (t > s and any(e["season"] == t for e in numbered)):
                    break
                chain.append((t, total))
                total += counts[t]
                if total >= len(mine):
                    break
            if total != len(mine):
                continue
            plan: dict[str, tuple[int, int, str]] | None = {}
            for e in numbered:
                if e["season"] != s or len(e["episodes"]) != 1:
                    continue
                n = e["episodes"][0]
                t, before = max((c for c in chain if c[1] < n), key=lambda c: c[1])
                tt = season(t).get(n - before)
                named = self.store.parsed("episode", [folder, *e["file"].split("/")]).episode_title
                other = by_title(named)
                if named and tt and not same_title(named, tt) and other and other[:2] != (t, n - before):
                    plan = None
                    break  # its title is clearly another episode's: not certain (a different translation is no reason)
                if (t, n - before) != (s, n) and plan is not None:
                    plan[e["file"]] = (t, n - before, tt or "")
            if plan is not None:
                out.update({f: v for f, v in plan.items() if f not in out})
                self._sized.add(s)  # its episodes up to TMDB's count are confirmed where they are
        # 3. a season numbered 1..N whose only episodes beyond TMDB's count are specials by their name (Shameless UK's
        #    "S02E11 Christmas Special"): the numbers up to the count are TMDB's; only the specials stay questions.
        for s in sorted({e["season"] for e in numbered}):
            if s not in counts or s in self._sized or not (size := len(season(s))):
                continue
            mine = [(n, e) for e in numbered if e["season"] == s for n in e["episodes"]]
            over = [e for n, e in mine if n > size]
            if over and all(SPECIAL_NAME.search(e["file"].rsplit("/", 1)[-1]) for e in over) and \
                    sorted(n for n, _ in mine if n <= size) == list(range(1, size + 1)):
                self._sized.add(s)
        return out

    def _listing(self, tmdb_id: int, seasons=None) -> dict[tuple[int, int], dict]:
        """A TMDB show's episodes, (season, episode) -> TMDB's episode: the seasons given, or all of them."""
        if seasons is None:
            seasons = [s["season_number"] for s in (self.tmdb.tv(tmdb_id) or {}).get("seasons", [])]
        return {(s, int(x["episode_number"])): x for s in seasons for x in (self.tmdb.tv_season(tmdb_id, s) or {}).get("episodes", [])}

    @staticmethod
    def _fits(f: tuple, listing: dict[tuple[int, int], dict], anywhere: bool) -> bool:
        """A file (episode, its title, the year in its name) is this show's: its title is TMDB's at its number (or
        anywhere in the show), or, without a real title ('Episode 1'), the year in its name is the year that episode aired."""
        e, named, year = f
        at = listing.get((e["season"], e["episodes"][0]))
        if named:
            return bool(at and same_title(named, at.get("name") or "")) or anywhere and any(
                same_title(named, x.get("name") or "") for x in listing.values())
        return bool(year and at and (at.get("air_date") or "")[:4] == str(year))

    def _rematch(self, folder: str, eps: list[dict], tmdb_id: int) -> dict | None:
        """A folder matched to the wrong show (26 Oct: 'Shameless' held the US series, matched to the UK one): the
        titles in its episodes' names are hardly the matched show's, and most are one other show's of that name.
        Only when certain: at least 6 titled episodes, under 30% fit the matched show, 70% or more the other one.
        The episodes that are the old show's ('strays') go to that show's folder, or to quarantine when it has them.

        Without episode titles (Magi's '[AnimeRG] Magi - The Labyrinth of Magic - 01', matched to 'MaXi'): when the
        folder's name is nothing like the matched show's names and TMDB places the folder's name with certainty on
        another show, as for a download."""
        files = []
        for e in eps:
            if e["season"] is None or not e["episodes"] or e["damaged"]:
                continue
            p = self.store.parsed("episode", [folder, *e["file"].split("/")])
            t = _bare(p.episode_title) if p.episode_title else ""
            files.append((e, t if len(t) >= 4 and not GENERIC_TITLE.match(t) else None, p.year))
        # A 'title' in three names or more is the show's name or a release tag, not an episode's (two-parters share one).
        seen = Counter(normalize(f[1]) for f in files if f[1])
        files = [(e, t if t and seen[normalize(t)] <= 2 else None, y) for e, t, y in files]
        titled = [f for f in files if f[1]]
        old_details = self.tmdb.tv(tmdb_id) or {}
        old_name = old_details.get("name") or "?"
        if old_details.get("first_air_date"):
            old_name += f" ({old_details['first_air_date'][:4]})"

        def share(listing: dict, anywhere: bool) -> float:
            return sum(self._fits(f, listing, anywhere) for f in titled) / len(titled)

        if len(titled) < 6:
            return self._rematch_by_name(folder, files, tmdb_id, old_details, old_name)
        seasons = sorted({f[0]["season"] for f in files})
        if share(self._listing(tmdb_id, seasons), False) >= 0.3:
            return None  # the usual case, decided on the seasons Health reads anyway
        old = self._listing(tmdb_id)
        if share(old, True) >= 0.3:
            return None  # another order or numbering, but this show's episodes
        p = parse_show_folder(folder)
        best, best_share, best_listing = None, 0.0, {}
        for r in (self.tmdb.search_tv(p.title or folder) or [])[:6]:
            if r.get("id") == tmdb_id:
                continue
            listing = self._listing(r["id"])
            if (s := share(listing, True)) > best_share:
                best, best_share, best_listing = r, s, listing
        if not best or best_share < 0.7:
            return None
        new_id = int(best["id"])
        details = self.tmdb.tv(new_id) or {}
        names = [best.get("name") or "", best.get("original_name") or "",
                 *[a.get("title") or "" for a in (details.get("alternative_titles") or {}).get("results", [])]]
        if best_similarity(p.title or folder, [n for n in names if n]) < 0.6:
            return None  # another show than the folder's name (26 Oct: 'Jiskefet' holds the spin-off 'Sint Hubertusberg')
        # The new show has to explain the folder, not only its titled files: most of all its episodes are that show's
        # (Jiskefet: 8 of 19 were the spin-off's).
        if sum(self._fits(f, best_listing, True) for f in files) < 0.7 * len(files):
            return None
        name = best.get("name") or folder
        year = (best.get("first_air_date") or "")[:4]
        mine, strays = [], []
        homes = [sh for sh in getattr(self, "_shows_of", {}).get(str(tmdb_id), []) if sh["folder"] != folder]
        for f in files:
            e = f[0]
            if self._fits(f, best_listing, False):
                mine.append([e["file"], e["season"], e["episodes"][0]])  # the new show's episode at its own number
                continue
            if not self._fits(f, old, True):
                continue  # neither show's for certain: left alone, judged against the new match next time
            s, n = e["season"], e["episodes"][0]
            home = homes[0] if homes else None
            if not home:
                continue  # the old show's, with no folder of its own: judged against the new match next time
            if any(x["season"] == s and n in x["episodes"] for x in home["episodes"]):
                strays.append({"file": e["file"], "to": None, "why": f"{home['folder']} has S{s:02d}E{n:02d} already"})
            else:
                where = next((x["file"].rsplit("/", 1)[0] for x in home["episodes"] if x["season"] == s and "/" in x["file"]), f"Season {s:02d}")
                strays.append({"file": e["file"], "to": f"{home['folder']}/{where}/{e['file'].rsplit('/', 1)[-1]}",
                               "why": f"{home['folder']} is that show's folder"})
        return {"path": f"TV/{folder}", "from": tmdb_id, "to": new_id, "show": name,
                "label": f"{folder}: {name}{f' ({year})' if year else ''}, not {old_name}",
                "why": f"{round(best_share * len(titled))} of {len(titled)} episode titles are {name}'s; "
                       f"{round(share(old, True) * len(titled))} are {old_name}'s",
                "episodes": mine, "strays": strays}

    def _rematch_by_name(self, folder: str, files: list[tuple], tmdb_id: int, old_details: dict, old_name: str) -> dict | None:
        p = parse_show_folder(folder)
        if not p.title or not files:
            return None
        names = [old_details.get("name") or "", old_details.get("original_name") or "",
                 *[a.get("title") or "" for a in (old_details.get("alternative_titles") or {}).get("results", [])]]
        if best_similarity(p.title, [n for n in names if n]) >= 0.6:
            return None  # the folder is called (nearly) what it is matched to
        wanted = {(f[0]["season"], n) for f in files for n in f[0]["episodes"]}
        m = identify_show(self.tmdb, p.title, p.year, p.country, wanted)
        if m.status != "auto" or not m.best or m.best.tmdb_id == tmdb_id:
            return None
        new_id = m.best.tmdb_id
        listing = self._listing(new_id, sorted({s for s, _ in wanted}))
        mine = [[f[0]["file"], f[0]["season"], f[0]["episodes"][0]] for f in files if (f[0]["season"], f[0]["episodes"][0]) in listing]
        return {"path": f"TV/{folder}", "from": tmdb_id, "to": new_id, "show": m.best.title,
                "label": f"{folder}: {m.best.title}{f' ({m.best.year})' if m.best.year else ''}, not {old_name}",
                "why": f"the folder's name is {m.best.title}'s, by its name, year and episodes; nothing like {old_name}",
                "episodes": mine, "strays": []}

    def order_map(self, group_id: str) -> dict[tuple[int, int], dict]:
        """One of TMDB's other orders for a show (DVD, production…; an 'episode group'): the library's (season,
        episode) → TMDB's episode, which keeps its own season_number and episode_number (the aired order)."""
        data = self.tmdb.get(f"/tv/episode_group/{group_id}", max_age=30 * 86400) or {}
        out: dict[tuple[int, int], dict] = {}
        for g in data.get("groups", []):
            m = re.search(r"(?i)season\s*(\d+)", g.get("name") or "")
            s = int(m.group(1)) if m else 0 if re.search(r"(?i)special", g.get("name") or "") else int(g.get("order") or 0)
            for ep in g.get("episodes", []):
                out[(s, int(ep.get("order") or 0) + 1)] = ep
        return out

    def show_order(self, folder: str) -> dict[tuple[int, int], dict] | None:
        """The order the reader chose for this show, if any (Health's 'Use another order')."""
        group = (self.store.get("library.orders") or {}).get(folder)
        return self.order_map(group) if group else None

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
        for t in f.get("twins", []):
            beside = f["nfoFile"].rsplit("/", 1)[0] + "/" if "/" in f["nfoFile"] else ""
            fixes["leftovers"].append({"path": f"Film/{beside}{t}", "why": TWIN})
        if f["nfo"] and f["file"] and f.get("year") and f["title"] and not f["others"] and f["file"].count("/") == (1 if f["folder"] else 0):
            # 'Title (Year)/Title (Year).mkv' from its NFO. A film with extra videos, or one a folder deeper, keeps its name.
            want = movie_path(f["title"], f["year"], os.path.splitext(f["file"])[1])
            new_folder = want.split("/")[0]
            taken = new_folder != (f["key"] if f["folder"] else None) and os.path.lexists(self._full(f"Film/{new_folder}"))
            if want != f["file"] and not taken:
                fixes["film-renames"].append({"path": f"Film/{f['file']}", "to": want, "folder": f["key"] if f["folder"] else None,
                                              "label": new_folder, "why": f"from {f['file'].split('/')[0]}"})
        if f["nfo"] and f["file"] and f.get("nfoFile") and str(f["ids"].get("tmdb", "")).isdigit() and int(f["ids"]["tmdb"]) > 0:
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
    def apply(self, plan: dict, kinds: list[str], kodi=None, job=None, backup=None) -> dict:
        """backup(items): muthur's watched backup, taken from Kodi right before any rename (rename.read_before)."""
        items = [(k, x) for k in FIXES if k in kinds and k != "kodi-entries" for x in plan["fixes"].get(k, [])]
        self._renamed: list[tuple[str, str]] = []
        self._before: dict | None = None  # Kodi's items before the renames; None: Kodi is off, so nothing is renamed
        if {"renames", "film-renames"} & set(kinds) and kodi and kodi.check().get("connected"):
            if job:
                job.begin("Reading what Kodi knows", 0)
            self._before = renaming.read_before(kodi, self.roots, backup)
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
            label = f"Kodi takes {len(self._renamed):,} new names"
            if job:
                job.begin(label, len(self._renamed))  # counted as Kodi takes each

            def took(old):
                renaming.forget(self.store, old)
                if job:
                    job.step, job.done = label, job.done + 1

            def scanning(what, seconds):
                if job:
                    job.step = renaming.scan_line(what, seconds)

            renaming.remember(self.store, self._renamed)  # until Kodi took each one, even across a restart
            summary["kodiRenames"] = renaming.follow_in_kodi(kodi, self._renamed, self.roots, self._before, done=took, scanning=scanning)
        if entries := plan["fixes"].get("kodi-entries", []) if "kodi-entries" in kinds else []:
            # After the renames: Kodi has their new entries by now.
            if job:
                job.begin(f"Kodi drops {len(entries):,} old entries", len(entries))
            r = kodi_entries.remove(kodi, entries, backup, (lambda d: setattr(job, "done", d)) if job else None)
            done["kodi-entries"] = r["done"]
            failed += r["failed"]
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
        """A new file, never over an existing one; an empty file in its place is replaced (a copy is kept)."""
        full = self._full(path)
        if data and os.path.isfile(full) and os.path.getsize(full) == 0:
            self.journal.replace(run, path, full, data, self.backups)
            return True
        return self.journal.create(run, path, full, data)

    def _nfo(self, run: int, path: str, data: bytes | None) -> None:
        """An item's NFO: written, or the fix fails with why (it never counts as done without a change)."""
        if not data:
            raise ValueError("TMDB gave nothing to write")
        full = self._full(path)
        if os.path.isfile(full) and os.path.getsize(full) > 0 and not read_nfo(full).readable:
            # Release notes or a bare link where Kodi looks for the NFO: kept in quarantine, a real NFO takes its place.
            self._quarantine(run, path, "Release notes (or a link) named like the video’s NFO, which Kodi can’t read; a real NFO took its place.")
        if not self._write(run, path, data):
            raise ValueError("an NFO is already there; check the library again")

    def _imdb_data(self, run, x, nfos):
        """Done for all shows at once, by the score refresh before the other fixes (web.py)."""

    def _leftovers(self, run, x, nfos):
        self._quarantine(run, x["path"], "A leftover in the library: a download site's note or other junk." if x.get("why") == "junk"
                         else "Release notes named like the video’s NFO but for capitals; Kodi could read them instead of the NFO."
                         if x.get("why") == TWIN else "A leftover in the library: it belonged to a video that is gone.")

    def _put(self, run: int, path: str, data: bytes | None) -> None:
        """A file written over what is there (a copy of the old one kept), or a new one."""
        if not data:
            return
        full = self._full(path)
        if os.path.isfile(full):
            self.journal.replace(run, path, full, data, self.backups)
        else:
            self.journal.create(run, path, full, data)

    def _show_rematch(self, run, x, nfos):
        """'This is another show': the folder's NFOs and artwork become the new show's (the old ones kept, so History
        can put them back), the old show's season artwork goes to quarantine, and the old show's episodes in it go to
        that show's folder, or to quarantine when it has them already."""
        lib, _, folder = x["path"].partition("/")
        show = self.tmdb.tv_full(x["to"])
        if not show:
            raise ValueError("TMDB didn't return the show")
        if not os.path.isdir(self._full(x["path"])):
            raise ValueError("the folder isn't there any more")
        keep = set(self.store.get("titles.keepOriginal", sorted(LATIN_SCRIPT)))
        title = display_title(show.get("name") or x["show"], show.get("original_name"), show.get("original_language"), keep)
        imdb_id = (show.get("external_ids") or {}).get("imdb_id")
        for s in x["strays"]:
            path = f"{x['path']}/{s['file']}"
            if not os.path.isfile(self._full(path)):
                continue
            d, stem = os.path.split(os.path.splitext(self._full(path))[0])
            if s["to"]:
                renaming.rename(self.journal, run, self.roots[lib], lib, f"{folder}/{s['file']}", s["to"])
                continue
            for n in [os.path.basename(self._full(path)), *renaming.sidecars(d, stem)]:
                self._quarantine(run, f"{path.rsplit('/', 1)[0]}/{n}", f"An episode of another show in {folder} ({s['why']}).")
        self._put(run, f"{x['path']}/tvshow.nfo", nfo_write.tvshow_nfo(show, title, self.imdb.rating(imdb_id)))
        nfos.append(f"{x['path']}/tvshow.nfo")
        for name, key, size in (("poster.jpg", "poster_path", "w780"), ("fanart.jpg", "backdrop_path", "w1280")):
            if show.get(key):
                self._put(run, f"{x['path']}/{name}", self.tmdb.image(show[key], size))
        if logo := nfo_write.best_logo(show):
            self._put(run, f"{x['path']}/clearlogo.png", self.tmdb.image(logo, "w500"))
        for n in sorted(os.listdir(self._full(x["path"]))):
            if OLD_ART.match(n):
                self._quarantine(run, f"{x['path']}/{n}", f"Artwork of the show {folder} was matched to before.")
        seasons: dict[int, list] = {}
        for file, s, ep in x["episodes"]:
            video = f"{x['path']}/{file}"
            if not os.path.isfile(self._full(video)):
                continue
            listed = seasons.setdefault(s, (self.tmdb.tv_season(x["to"], s) or {}).get("episodes", []))
            tm = next((e for e in listed if e.get("episode_number") == ep), None)
            if not tm:
                continue
            stem = video.rsplit(".", 1)[0]
            self._put(run, stem + ".nfo", nfo_write.episode_nfo(title, s, tm, x["to"], number=ep,
                                                                 imdb=self.imdb.episode(imdb_id, s, ep, len(listed))))
            nfos.append(stem + ".nfo")
            if tm.get("still_path"):
                self._put(run, stem + "-thumb.jpg", self.tmdb.image(tm["still_path"], "original"))
        year = int(show["first_air_date"][:4]) if (show.get("first_air_date") or "")[:4].isdigit() else None
        self.store.remember("tv", title, x["to"], year, title, folder, "confirmed")
        self.scores._shows.pop(folder, None)  # read from the new tvshow.nfo next time

    def _subtitle_timing(self, run, x, nfos):
        """A subtitle file at another speed or shifted (another release): stretched to fit the video, measured against
        the subtitles inside it (subfit). The original goes to quarantine, so History can put it back."""
        full = self._full(x["path"])
        if not os.path.isfile(full):
            raise ValueError("it isn't there any more")
        with open(full, "rb") as fh:
            fixed = subfit.retime(fh.read(), x["shift"], x["speed"])
        self._quarantine(run, x["path"], f"Subtitles out of sync with the video ({x['why']}); a stretched copy took their place.")
        if not self.journal.create(run, x["path"], full, fixed):
            raise ValueError("the stretched copy couldn't be written")

    def _extras(self, run, x, nfos):
        """An interview, featurette, opening… beside the episodes, moved with its sidecars into the show's 'Extras' folder.
        Kodi never listed it (no episode number), so it needs no Kodi step; Kodi's Extras add-on looks there."""
        lib, _, rel = x["path"].partition("/")
        folder = rel.split("/", 1)[0]
        if not os.path.isfile(self._full(x["path"])):
            raise ValueError("it isn't there any more")
        renaming.rename(self.journal, run, self.roots[lib], lib, rel, f"{folder}/{x['to']}")

    def _subtitle_misfit(self, run, x, nfos):
        self._quarantine(run, x["path"], "Subtitles that don't fit this video (another cut of the film): stretching can't fix them.")

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
        # In another order the file's own numbers go into the NFO; TMDB and IMDb are asked by the aired ones.
        ts, te = x.get("aired") or (x["season"], x["episode"])
        listed = (self.tmdb.tv_season(x["tmdb"], ts) or {}).get("episodes", [])
        ep = next((e for e in listed if e.get("episode_number") == te), None)
        if not ep:
            raise ValueError("TMDB didn't return the episode")
        score = self.imdb.episode(x["imdbShow"], ts, te, len(listed))
        data = nfo_write.episode_nfo(x["show"], x["season"], ep, x["tmdb"], number=x["episode"], imdb=score)
        if x.get("replace") and os.path.isfile(self._full(x["path"])):
            # A renumbered episode: its NFO still says the old number. Replaced, with a copy of the old one kept.
            self.journal.replace(run, x["path"], self._full(x["path"]), data, self.backups)
        else:
            self._nfo(run, x["path"], data)
        nfos.append(x["path"])
        if x.get("thumb") and ep.get("still_path"):
            self._write(run, x["thumb"], self.tmdb.image(ep["still_path"], "original"))

    def _show_nfos(self, run, x, nfos):
        show = self.tmdb.tv_full(x["tmdb"])
        if not show:
            raise ValueError("TMDB didn't return the show")
        imdb_id = (show.get("external_ids") or {}).get("imdb_id")
        self._nfo(run, x["path"], nfo_write.tvshow_nfo(show, show.get("name") or x["label"], self.imdb.rating(imdb_id)))
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
        self._nfo(run, x["path"], nfo_write.movie_nfo(movie, title, self.imdb.rating(imdb_id)))
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
        if new is None:
            raise ValueError("its NFO has no place for a score (it may be empty or not an NFO); check the library again")
        self.scores._rewrite(run, full, text, new)
        nfos.append(x["path"])

