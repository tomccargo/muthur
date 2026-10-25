"""Duplicates: more than one video of the same episode or film (ARCHITECTURE.md §9).

Groups come from the library index. Each copy is measured with ffprobe (resolution, codec,
audio, duration) plus the source in its name (Blu-ray, WEB-DL, ...), and ranked in the order of
§9. The proposal keeps the best copy; when another copy owns the library name (it has the NFO
and artwork), the kept video takes over that name, so the NFO and thumbnail still match. Every
other copy goes to quarantine. Nothing happens until the reader confirms a group.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from guessit import guessit

from .media import probe
from .parse import SEASON_DIR, SPECIALS_DIR, is_video
from .text import normalize

SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup")

SCHEMA = "CREATE TABLE IF NOT EXISTS probe_cache (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL, body TEXT NOT NULL);"
CURATED = re.compile(r"^.+ \((19|20)\d{2}\)$")  # 'Dune (2021)': a folder named as the library names films

SOURCES = [  # §9, best first; a name that says nothing ranks with HDTV, between WEB and DVD
    ("remux", 7), ("ultra hd blu-ray", 6), ("blu-ray", 6), ("web-dl", 5), ("webrip", 4), ("hd-dvd", 4),
    ("unknown", 3), ("hdtv", 3), ("dvd", 2), ("vhs", 1), ("tv", 1), ("telesync", 0), ("camera", 0),
]
SOURCE_LABEL = {"remux": "Blu-ray remux", "ultra hd blu-ray": "UHD Blu-ray", "blu-ray": "Blu-ray", "web-dl": "WEB-DL",
                "webrip": "WEBRip", "hd-dvd": "HD DVD", "unknown": "", "hdtv": "HDTV", "dvd": "DVD", "vhs": "VHS", "tv": "TV",
                "telesync": "Telesync", "camera": "Cam"}
LOSSLESS = {"truehd", "flac", "pcm_s16le", "pcm_s24le", "pcm_bluray", "mlp"}


def _source(name: str) -> str:
    g = guessit(name, {"type": "episode"})
    src = g.get("source")
    src = (src[0] if isinstance(src, list) else src or "").lower()
    other = g.get("other") or []
    other = [o.lower() for o in (other if isinstance(other, list) else [other])]
    if "remux" in other:
        return "remux"
    if src == "web":
        return "webrip" if "rip" in other else "web-dl"
    if src in ("ultra hd blu-ray", "blu-ray", "hd-dvd", "hdtv", "dvd", "vhs", "telesync", "camera"):
        return src
    if src in ("analog hdtv", "digital tv", "tv"):
        return "tv" if src != "analog hdtv" else "hdtv"
    return "unknown"


def _resolution(width: int, height: int) -> int:
    """2160p = 4 ... SD = 0, by the larger of width and height so a 1920x800 film counts as 1080p."""
    for rank, (w, h) in ((4, (3700, 2000)), (3, (1880, 1000)), (2, (1240, 700)), (1, (700, 470))):
        if width >= w or height >= h:
            return rank
    return 0


def quality(path: str, size: int, facts: dict | None, subs: int) -> dict:
    name = os.path.basename(path)
    src = _source(name)
    q = {"source": src, "readable": facts is not None, "size": size, "subs": subs}
    if facts:
        codec = (facts.get("vcodec") or "").lower()
        acodec = (facts.get("acodec") or "").lower()
        lossless = acodec in LOSSLESS or (acodec == "dts" and "ma" in (facts.get("aprofile") or "").lower())
        q.update(width=facts["width"], height=facts["height"], vcodec=codec, acodec=acodec, channels=facts["channels"],
                 duration=facts["duration"], subs=subs + facts.get("subtitles", 0),
                 kbps=round(size * 8 / facts["duration"] / 1000) if facts["duration"] else 0)
        q["rank"] = [dict(SOURCES)[src], _resolution(facts["width"], facts["height"]),
                     3 if codec in ("hevc", "av1") else 2 if codec == "h264" else 1,
                     3 if lossless else 2 if facts["channels"] >= 6 else 1 if facts["channels"] else 0,
                     q["kbps"], 1 if q["subs"] else 0]
    else:
        q["rank"] = [-1]  # a copy ffprobe can't read is never the one to keep
    return q


def describe(q: dict) -> str:
    """'Blu-ray · 1080p · HEVC · 5.1 · 4.2 Mbit/s' for the page."""
    if not q.get("readable"):
        return "ffprobe can't read this file"
    res = {4: "2160p", 3: "1080p", 2: "720p", 1: "576p/480p", 0: "SD"}[_resolution(q["width"], q["height"])]
    audio = "lossless" if q["rank"][3] == 3 else "5.1" if q["channels"] >= 6 else "stereo" if q["channels"] >= 2 else "mono" if q["channels"] else "no audio"
    parts = [SOURCE_LABEL.get(q["source"], ""), res, {"hevc": "HEVC", "h264": "H.264", "av1": "AV1"}.get(q["vcodec"], (q["vcodec"] or "?").upper()),
             audio, f"{q['kbps'] / 1000:.1f} Mbit/s" if q.get("kbps") else ""]
    return " · ".join(p for p in parts if p)


class Duplicates:
    def __init__(self, store, tv_root: str, film_root: str):
        self.store, self.roots = store, {"TV": tv_root, "Film": film_root}
        with store.lock:
            store.db.execute(SCHEMA)
            store.db.commit()

    def _probe(self, path: str) -> dict | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        with self.store.lock:
            row = self.store.db.execute("SELECT size, mtime, body FROM probe_cache WHERE path = ?", (path,)).fetchone()
        if row and row[0] == st.st_size and row[1] == st.st_mtime:
            return json.loads(row[2])
        facts = probe(path)
        with self.store.lock:
            self.store.db.execute("INSERT OR REPLACE INTO probe_cache VALUES (?, ?, ?, ?)", (path, st.st_size, st.st_mtime, json.dumps(facts)))
            self.store.db.commit()
        return facts

    # -- finding groups ------------------------------------------------------------------
    def find(self, library: dict, job=None) -> list[dict]:
        raw = []
        for show in library.get("shows", []):
            raw += [("episode", show, g) for g in _episode_groups(show["episodes"])]
        raw += [("film", None, g) for g in _film_groups(library.get("films", []))]
        if job:
            job.total, job.done = len(raw), 0
        out = []
        for kind, show, copies in raw:
            out.append(self._group(kind, show, copies))
            if job:
                job.done += 1
        return out

    def _group(self, kind: str, show: dict | None, copies: list[dict]) -> dict:
        lib = "TV" if kind == "episode" else "Film"
        root = self.roots[lib]
        items = []
        for c in copies:
            rel = f"{show['folder']}/{c['file']}" if kind == "episode" else c["file"]
            full = os.path.join(root, *rel.split("/"))
            q = quality(full, c["size"], self._probe(full), c.get("subs", 0))
            items.append({"path": f"{lib}/{rel}", "nfo": c["nfo"], "muthur": c.get("muthur", False), "watched": c.get("watched"),
                          "unit": c.get("key"), "folder": c.get("folder", False), "quality": q, "label": describe(q)})
        # Best quality first; between equals, the copy with an NFO in a proper season or show folder.
        items.sort(key=lambda x: (x["quality"]["rank"], x["nfo"], _proper(x["path"]), x["muthur"]), reverse=True)
        keep = items[0]
        if kind == "episode":
            e = copies[0]
            label = f"{show['title']} S{e['season']:02d}" + "".join(f"E{n:02d}" for n in e["episodes"])
        else:
            label = f"{copies[0]['title']}{' (' + str(copies[0]['year']) + ')' if copies[0].get('year') else ''}"
        group = {"id": hashlib.sha1("|".join(sorted(i["path"] for i in items)).encode()).hexdigest()[:12], "kind": kind,
                 "label": label, "title": show["title"] if show else copies[0]["title"], "show": show["folder"] if show else None,
                 "copies": items, "keep": keep["path"]}
        same = len({(i["quality"]["size"], tuple(i["quality"]["rank"])) for i in items}) == 1
        group["note"] = "The copies are the same file." if same else None
        group["plan"] = self.plan(group, keep["path"])
        return group

    # -- the plan for one group --------------------------------------------------------------
    def plan(self, group: dict, keep: str) -> dict:
        """What confirming does when `keep` is the copy to keep: [{op, src, dst}] relative to the
        library roots, in order, plus the kept video's final path.

        The kept video takes the name of the best-named copy (its 'home'), so that copy's NFO and
        thumbnail keep matching. Sidecars come from the kept copy first, then from the home copy;
        a subtitle the kept copy lacks comes from any copy. Everything else goes to quarantine."""
        copies = group["copies"]
        kept = next(c for c in copies if c["path"] == keep)
        folders = group["kind"] == "film" and any(c["folder"] for c in copies)
        if folders:
            # Films in folders: the best-named folder with an NFO stays and receives the kept video.
            home = max(copies, key=lambda c: (c["folder"], c["nfo"], c["folder"] and bool(CURATED.match(_unit_dir(c))), c is kept))
            home_dir = _unit_dir(home) if home["folder"] else None
            final_stem = f"Film/{home_dir}/{home_dir}" if home_dir and CURATED.match(home_dir) else _stem(home["path"])
            sources = [kept] if home is kept else [kept, home]
        else:
            home = _owner(copies, kept, group["title"])
            final_stem = _with_resolution(_stem(home["path"]), kept["quality"])
            sources = copies
        final = final_stem + os.path.splitext(keep)[1]

        first, moves, last = [], [], []  # files out of the way, then renames, then whole folders
        by_suffix: dict[str, list[tuple[dict, str]]] = {}
        for c in sources:
            for side in self._sidecars(c["path"]):
                by_suffix.setdefault(side[len(_stem(c["path"])):], []).append((c, side))
        for suffix, found in by_suffix.items():
            pick = next((s for c, s in found if c is kept), None) or next((s for c, s in found if c is home), None)
            if pick is None and suffix.lower().endswith(SUBTITLE_EXTS):
                pick = found[0][1]
            for _, side in found:
                if side != pick:
                    first.append({"op": "quarantine", "src": side})
                elif side != final_stem + suffix:
                    moves.append({"op": "move", "src": side, "dst": final_stem + suffix})
        for c in sources:
            if c is not kept:
                first.append({"op": "quarantine", "src": c["path"]})
        if keep != final:
            moves.append({"op": "move", "src": keep, "dst": final})
        for c in copies:
            if c in sources:
                continue
            if c["folder"]:
                last.append({"op": "quarantine", "src": f"Film/{_unit_dir(c)}"})
            else:
                first += [{"op": "quarantine", "src": x} for x in [c["path"], *self._sidecars(c["path"])]]
        if folders and kept is not home and kept["folder"]:
            last.append({"op": "quarantine", "src": f"Film/{_unit_dir(kept)}"})  # what's left of the kept copy's folder
        return {"final": final, "ops": first + moves + last}

    def _sidecars(self, path: str) -> list[str]:
        """Files next to a video that belong to it: 'x.nfo', 'x-thumb.jpg', 'x.en.srt'."""
        lib, _, rel = path.partition("/")
        full = os.path.join(self.roots[lib], *rel.split("/"))
        folder, stem = os.path.dirname(full), os.path.splitext(os.path.basename(full))[0]
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        base = path.rsplit("/", 1)[0]
        return sorted(f"{base}/{n}" for n in names
                      if n != os.path.basename(full) and n.startswith(stem) and n[len(stem):len(stem) + 1] in (".", "-") and not is_video(n))


def _stem(path: str) -> str:
    return os.path.splitext(path)[0]


def _unit_dir(c: dict) -> str:
    return c["path"].split("/")[1]


def _unit_dir_of(path: str) -> str | None:
    parts = path.split("/")
    return parts[1] if len(parts) > 2 else None


def _owner(copies: list[dict], kept: dict, title: str) -> dict:
    """The copy whose name the kept video takes: one with an NFO, preferably written by muthur and
    named after the show ('Game of Thrones S07E06 - Beyond the Wall' over 'GOT S07E06')."""
    with_nfo = [c for c in copies if c["nfo"]]
    if not with_nfo:
        return kept
    show = normalize(title)
    return max(with_nfo, key=lambda c: (c["muthur"], normalize(os.path.basename(c["path"])).startswith(show), c is kept))


def _proper(path: str) -> bool:
    """In the show or film folder itself, or in a season folder; not in a leftover release folder."""
    parts = path.split("/")
    return len(parts) <= 3 or bool(SEASON_DIR.match(parts[-2]) or SPECIALS_DIR.match(parts[-2]))


RESOLUTION_TOKEN = re.compile(r"(?<![A-Za-z0-9])(2160p|1080p|720p|576p|480p|SD)(?![A-Za-z0-9])")


def _with_resolution(stem: str, q: dict) -> str:
    """A name that states a resolution says the kept copy's: '… - 480p' becomes '… - 1080p'."""
    folder, _, name = stem.rpartition("/")
    found = RESOLUTION_TOKEN.findall(name)
    if len(found) != 1 or not q.get("readable"):
        return stem
    res = {4: "2160p", 3: "1080p", 2: "720p", 1: "480p", 0: "SD"}[_resolution(q["width"], q["height"])]
    return f"{folder}/{RESOLUTION_TOKEN.sub(res, name)}"


def _episode_groups(episodes: list[dict]) -> list[list[dict]]:
    """Files of one show that share an episode number, joined when a double episode links them.
    Files with a damaged number are left out: their numbers don't mean anything."""
    eps = [e for e in episodes if e["season"] is not None and e["episodes"] and not e["damaged"] and not e["sample"]]
    parent = list(range(len(eps)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[tuple, int] = {}
    for i, e in enumerate(eps):
        for n in e["episodes"]:
            k = (e["season"], n)
            if k in first:
                parent[find(i)] = find(first[k])
            else:
                first[k] = i
    groups: dict[int, list[dict]] = {}
    for i, e in enumerate(eps):
        groups.setdefault(find(i), []).append(e)
    return [g for g in groups.values() if len(g) > 1]


def _film_groups(films: list[dict]) -> list[list[dict]]:
    """Films that share an IMDb or TMDB ID."""
    by_id: dict[tuple, list[int]] = {}
    for i, f in enumerate(films):
        if not f.get("file"):
            continue
        for kind in ("imdb", "tmdb"):
            if f["ids"].get(kind):
                by_id.setdefault((kind, f["ids"][kind]), []).append(i)
    parent = list(range(len(films)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for idxs in by_id.values():
        for i in idxs[1:]:
            parent[find(i)] = find(idxs[0])
    groups: dict[int, list[dict]] = {}
    for i, f in enumerate(films):
        if f.get("file"):
            groups.setdefault(find(i), []).append(f)
    return [g for g in groups.values() if len(g) > 1]


class Stop(Exception):
    """A reason not to touch a group, as a sentence for the reader."""


def apply_groups(dups: Duplicates, groups: list[dict], journal, quarantine: str, kodi=None, job=None) -> dict:
    """Carry out the plans of these groups (each with its chosen 'keep' and 'plan'). With Kodi, the
    watched status of every copy is read first and given to the kept video afterwards (§11)."""
    from .watched import Watched

    before, prefixes = {}, {}
    if kodi:
        prefixes = {lib: kodi.source_prefix(lib) for lib in ("TV", "Film")}
        for i in Watched.read_kodi(kodi):
            for lib, pre in prefixes.items():
                if pre and (i["file"] or "").lower().startswith(pre.lower()):
                    before[f"{lib}/{i['file'][len(pre):]}".lower()] = i
    run = journal.start("duplicates")
    results = []
    if job:
        job.total, job.done = len(groups), 0
    for g in groups:
        try:
            _apply_one(dups, journal, run, g, quarantine)
            results.append({"id": g["id"], "label": g["label"], "ok": True, "final": g["plan"]["final"]})
        except Stop as e:
            journal.undo(run, g["id"])
            results.append({"id": g["id"], "label": g["label"], "ok": False, "why": str(e)})
        except Exception as e:  # put this group back as it was
            back = journal.undo(run, g["id"])
            why = f"It went wrong halfway ({type(e).__name__}: {e}); muthur put back what it had changed."
            if back["skipped"]:
                why += f" {len(back['skipped'])} change(s) could not be put back; see History."
            results.append({"id": g["id"], "label": g["label"], "ok": False, "why": why})
        if job:
            job.done += 1
    if kodi:
        for r in results:
            if r["ok"]:
                g = next(x for x in groups if x["id"] == r["id"])
                r["kodi"] = _carry(kodi, g, before, prefixes)
    summary = {"applied": sum(r["ok"] for r in results), "stopped": sum(not r["ok"] for r in results), "items": results}
    journal.finish(run, summary)
    return {"run": run, **summary}


def _full(dups: Duplicates, path: str) -> str:
    lib, _, rel = path.partition("/")
    return os.path.join(dups.roots[lib], *rel.split("/"))


def _apply_one(dups: Duplicates, journal, run: int, g: dict, quarantine: str) -> None:
    import time

    from .journal import fingerprint

    # 1. Checks before anything changes: every copy is still what muthur measured.
    for c in g["copies"]:
        full = _full(dups, c["path"])
        if not os.path.isfile(full):
            raise Stop(f"{c['path']} isn't there any more. Check the duplicates again.")
        if os.path.getsize(full) != c["quality"]["size"]:
            raise Stop(f"{c['path']} changed since muthur measured it. Check the duplicates again.")
    leaving = {o["src"] for o in g["plan"]["ops"]}
    for o in g["plan"]["ops"]:
        if o["op"] == "move" and os.path.lexists(_full(dups, o["dst"])) and o["dst"] not in leaving:
            raise Stop(f"{o['dst']} already exists; muthur never overwrites.")

    # 2. The changes, each journalled before it happens.
    day = time.strftime("%Y-%m-%d")

    def mkdirs(path: str) -> None:
        missing, p = [], path
        while not os.path.isdir(p):
            missing.append(p)
            p = os.path.dirname(p)
        for d in reversed(missing):
            os.mkdir(d)
            journal.record(run, g["id"], "mkdir", None, d)

    def move(src: str, dst: str, op: str) -> None:
        if os.path.lexists(dst):
            raise Stop(f"{dst} already exists; muthur never overwrites.")
        mkdirs(os.path.dirname(dst))
        size = os.path.getsize(src) if os.path.isfile(src) else None
        op_id = journal.record(run, g["id"], op, src, dst, size, status="failed")
        os.rename(src, dst)
        digest = fingerprint(dst) if size is not None else None
        with journal.store.lock:
            journal.store.db.execute("UPDATE ops SET status = 'done', digest = ? WHERE id = ?", (digest, op_id))
            journal.store.db.commit()

    for o in g["plan"]["ops"]:
        src = _full(dups, o["src"])
        if not os.path.lexists(src):
            continue  # a sidecar that is already gone
        if o["op"] == "quarantine":
            dst = os.path.join(quarantine, day, *o["src"].split("/"))
            if os.path.lexists(dst):
                dst += f" ({int(time.time())})"
            move(src, dst, "quarantine")
            from . import quarantine as notes

            notes.note(quarantine, dst, o["src"], run, f"Another copy of {g['label']} was kept: {g['plan']['final']}.")
        else:
            move(src, _full(dups, o["dst"]), "move")


def _carry(kodi, g: dict, before: dict, prefixes: dict) -> dict:
    """After a group changed on disk: Kodi scans the kept video's folder, the kept item gets the
    highest play count and resume point of all copies, and entries for the old files go."""
    lib, _, rel = g["plan"]["final"].partition("/")
    prefix = prefixes.get(lib)
    if not prefix:
        return {"ok": False, "why": f"Kodi has no source called {lib}."}
    states = [before[c["path"].lower()] for c in g["copies"] if c["path"].lower() in before]
    playcount = max((s["playcount"] for s in states), default=0)
    lastplayed = max((s["lastplayed"] for s in states if s["lastplayed"]), default=None)
    resume = max((s for s in states if s["resume"] > 0), key=lambda s: s["resume"], default=None)
    final_file = prefix + rel
    try:
        kodi.scan_and_wait(final_file.rsplit("/", 1)[0] + "/")
        method, key, id_key = (("VideoLibrary.GetEpisodes", "episodes", "episodeid") if g["kind"] == "episode"
                               else ("VideoLibrary.GetMovies", "movies", "movieid"))
        found = kodi.call(method, {"properties": ["file", "playcount", "resume"],
                                   "filter": {"field": "filename", "operator": "is", "value": rel.rsplit("/", 1)[-1]}}) or {}
        item = next((x for x in found.get(key, []) if x["file"].lower() == final_file.lower()), None)
        if not item:
            return {"ok": False, "why": "Kodi didn't list the kept file after scanning its folder."}
        setter = "VideoLibrary.SetEpisodeDetails" if g["kind"] == "episode" else "VideoLibrary.SetMovieDetails"
        params = {id_key: item[id_key]}
        if playcount > (item.get("playcount") or 0):
            params.update(playcount=playcount, **({"lastplayed": lastplayed} if lastplayed else {}))
        elif not playcount and resume and not (item.get("resume") or {}).get("position"):
            params["resume"] = {"position": resume["resume"], "total": resume["total"]}
        if len(params) > 1:
            kodi.call(setter, params)
        remover = "VideoLibrary.RemoveEpisode" if g["kind"] == "episode" else "VideoLibrary.RemoveMovie"
        removed = 0
        for s in states:
            if s["kodiid"] != item[id_key]:
                try:
                    kodi.call(remover, {id_key: s["kodiid"]})
                    removed += 1
                except RuntimeError:
                    pass  # already gone
        return {"ok": True, "playcount": playcount, "removed": removed}
    except Exception as e:  # the files are done; Kodi catching up is reported, not undone
        return {"ok": False, "why": f"Kodi didn't take it all: {e}"}
