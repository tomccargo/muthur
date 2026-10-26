"""The FastAPI app: a small JSON API plus the built React UI. One process, one worker."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__
from .auth import COOKIE, SESSION_SECONDS, Auth, same_site
from .config import load_dotenv
from .apply import Applier
from .imdb import REFRESH_DAYS, Imdb
from .downloadstation import DownloadStation, DownloadStationError
from .opensubs import OpenSubtitles, OpenSubtitlesError
from .duplicates import Duplicates, apply_groups
from .health import FIXES, Health
from .inbox import Inbox
from .library_edit import LibraryEdit
from .index import Index
from .jobs import Busy, Jobs
from .journal import Journal
from .kodi import Kodi, folder_name
from .memory import import_tv
from .naming import LATIN_SCRIPT
from .parse import parse_show_folder
from . import nfo_write, player, subfit
from . import quarantine as quarantine_notes
from . import rename as renaming
from .scores import ScoreRefresh
from .shield import COMPONENT, Shield, ShieldError
from .store import Store
from .text import count
from .tmdb import Tmdb
from .watched import Listener, Watched


class Config:
    """Paths from the environment (compose.yaml sets them from .env); the defaults match compose.yaml's."""

    def __init__(self, dotenv: bool = True):
        if dotenv:
            load_dotenv()
        self.config_dir = os.environ.get("MUTHUR_CONFIG", "/config")
        self.downloads = os.environ.get("MUTHUR_DOWNLOADS", "/data/downloads/complete")
        self.tv = os.environ.get("MUTHUR_TV", "/data/TV")
        self.film = os.environ.get("MUTHUR_FILM", "/data/Film")
        self.quarantine = os.environ.get("MUTHUR_QUARANTINE", "/data/_muthur-quarantine")
        self.web_dist = os.environ.get("MUTHUR_WEB", str(Path(__file__).resolve().parents[2] / "web" / "dist"))
        # The weekly IMDb refresh runs on its own; tests and one-off tools switch it off.
        self.scheduler = os.environ.get("MUTHUR_SCHEDULER", "1") != "0"
        # The UI asks for a password (§14). Only tests, or a proxy in front with its own login, switch it off.
        self.auth = os.environ.get("MUTHUR_AUTH", "1") != "0"


TMDB_LINK = re.compile(r"themoviedb\.org/(tv|movie)/(\d+)")
TMDB_LANGUAGE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")  # 'en-US', 'nl-BE': what TMDB's language parameter takes
IMDB_ID = re.compile(r"\b(tt\d{6,10})\b")


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def _card(kind: str, r: dict) -> dict:
    """A TMDB search result or details as one card on the Review page."""
    return {"kind": kind, "tmdbId": r["id"], "title": r.get("name") or r.get("title") or "",
            "originalTitle": r.get("original_name") or r.get("original_title") or "",
            "year": _year(r.get("first_air_date") or r.get("release_date")),
            "overview": r.get("overview") or "", "poster": r.get("poster_path")}


def _choice(body: dict) -> tuple[str, dict]:
    """The item id and a cleaned-up choice from a Review request."""
    item_id = str(body.get("id") or "")
    c = body.get("choice") or {}
    if c.get("kind") not in ("tv", "movie") or not str(c.get("tmdbId", "")).isdigit():
        raise HTTPException(422, "Choose a show or a film first.")
    episodes = {}
    for source, m in (c.get("episodes") or {}).items():
        try:
            episodes[str(source)] = {"season": int(m["season"]), "episode": int(m["episode"]),
                                     "part": int(m["part"]) if m.get("part") else None,
                                     "number": "tmdb" if m.get("number") == "tmdb" else "file"}
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "An episode choice is incomplete: pick the episode it is.")
    return item_id, {"kind": c["kind"], "tmdbId": int(c["tmdbId"]), "episodes": episodes}


def _ascii(name: str) -> str:
    """A file name for a Content-Disposition header: plain ASCII, no quotes (the header can't carry more)."""
    return re.sub(r"[^\x20-\x7e]|\"", "_", name)


def _ep_key(e: dict) -> tuple | None:
    return (e["season"], tuple(e["episodes"])) if e["season"] is not None and e["episodes"] else None


def _duplicates(episodes: list[dict]) -> set:
    """Episode numbers that more than one video file in a show claims (S04E14 twice, or S01E01 and S01E01E02)."""
    seen: dict[tuple, int] = {}
    for e in episodes:
        if e["season"] is not None:
            for n in e["episodes"]:
                seen[(e["season"], n)] = seen.get((e["season"], n), 0) + 1
    return {_ep_key(e) for e in episodes if e["season"] is not None and any(seen[(e["season"], n)] > 1 for n in e["episodes"])}


def _show_summary(sh: dict) -> dict:
    eps = sh["episodes"]
    return {
        "folder": sh["folder"], "title": sh["title"], "year": sh["year"], "ids": sh["ids"], "nfo": sh["nfo"],
        "poster": sh["poster"], "rating": sh["rating"], "count": len(eps),
        "seasons": len({e["season"] for e in eps if e["season"] is not None}),
        "watched": sum(1 for e in eps if e["watched"]), "size": sum(e["size"] for e in eps),
        "problems": {"noNfo": sum(not e["nfo"] for e in eps) + (0 if sh["nfo"] else 1),
                     "noScore": sum(not e["imdb"] for e in eps), "duplicates": len(_duplicates(eps)),
                     "damaged": sum(1 for e in eps if e["damaged"] or e["season"] is None), "loose": len(sh["loose"])},
    }


def _twins(films: list[dict]) -> list[int]:
    """For each film, how many other films share its TMDB or IMDb ID (one pass, not every pair)."""
    by_id: dict[tuple, set[int]] = {}
    for i, f in enumerate(films):
        for k, v in f["ids"].items():
            if k in ("tmdb", "imdb"):
                by_id.setdefault((k, v), set()).add(i)
    return [len(set().union(*(by_id[(k, v)] for k, v in f["ids"].items() if k in ("tmdb", "imdb"))) - {i})
            for i, f in enumerate(films)]


def _plan_check(plan: list[dict]) -> str:
    """A short fingerprint of a restore plan: the preview and the restore must be the same plan."""
    rows = sorted(json.dumps([c["kind"], c["kodiid"], c["what"], c.get("playcount"), c.get("resume")]) for c in plan)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


def _film_summary(f: dict, twins: int) -> dict:
    return {**f, "problems": {"noNfo": int(not f["nfo"]), "noScore": int(not f["imdb"]), "duplicates": twins,
                              "damaged": len([x for x in f["flags"] if x != "multiple-main-videos"]), "loose": 0}}


def _size(path: str) -> int:
    """Bytes in a folder; a file that vanished or a broken link counts as nothing."""
    total = 0
    for dp, _, names in os.walk(path):
        for n in names:
            try:
                total += os.lstat(os.path.join(dp, n)).st_size
            except OSError:
                pass
    return total


def _question_key(q: dict) -> str:
    """A Health question as the reader left it: its place and its wording. When the files change, the
    check words it differently (or finds another place), and it is asked again."""
    return f"{q['path']}|{q.get('season')}|{q['why']}"


def _path_state(path: str) -> dict:
    exists = os.path.isdir(path)
    return {"path": path, "exists": exists, "readable": exists and os.access(path, os.R_OK),
            "writable": exists and os.access(path, os.W_OK)}


def create_app(cfg: Config | None = None, tmdb_factory=None) -> FastAPI:
    """tmdb_factory(token, cache_path): lets tests use a fake TMDB."""
    cfg = cfg or Config()
    tmdb_factory = tmdb_factory or Tmdb
    os.makedirs(cfg.config_dir, exist_ok=True)
    store = Store(os.path.join(cfg.config_dir, "muthur.db"))
    journal = Journal(store)
    imdb = Imdb(store)
    watched = Watched(store)
    index = Index(store, cfg.tv, cfg.film)
    dups = Duplicates(store, cfg.tv, cfg.film)
    jobs = Jobs()
    JOB_NAMES = {"inbox": "Checking the downloads", "apply": "Filing downloads", "undo": "Putting a run back",
                 "memory": "Learning the shows", "scores": "Refreshing IMDb scores", "library": "Indexing the library",
                 "duplicates": "Looking for duplicates", "duplicates-apply": "Resolving duplicates",
                 "health": "Checking the library", "fixes-apply": "Fixing the library", "kodi-refresh": "Telling Kodi what changed",
                 "rename": "Renaming an episode", "kodi-renames": "Telling Kodi the new names", "player-scan": "Reading how each video plays",
                 "subtitles-extract": "Copying subtitles out of a video"}
    app = FastAPI(title="muthur", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    tmdb_cache: dict = {}
    auth = Auth(store, cfg.auth)
    OPEN = {"/api/health", "/api/auth", "/api/auth/login", "/api/auth/setup", "/api/auth/logout"}
    # A video and its .srt files for a player outside the browser, with a link key instead of the sign-in (Auth.link_key).
    LINKED = re.compile(r"^/api/player/video/([0-9a-f]{16})(?:/sidecar/[^/]+)?$")
    BUSY = "Another job is running. Try again when it's done."

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Every API request: a change a browser says comes from another site is refused, and only a
        signed-in browser gets an answer (§14)."""
        path = request.url.path
        if path.startswith("/api/"):
            if request.method not in ("GET", "HEAD", "OPTIONS") and not same_site(request.headers):
                return JSONResponse({"detail": "Refused: this request came from another website."}, status_code=403)
            linked = request.method == "GET" and (m := LINKED.match(path)) and auth.link_valid(m.group(1), request.query_params.get("key"))
            if auth.required and path not in OPEN and not linked and not await run_in_threadpool(auth.valid, request.cookies.get(COOKIE)):
                return JSONResponse({"detail": "Sign in to muthur first.", "auth": "login" if auth.is_set() else "setup"},
                                    status_code=401)
        return await call_next(request)

    @contextmanager
    def alone(name: str):
        """A change made in the request itself, never while a job runs (and no job starts meanwhile)."""
        try:
            with jobs.exclusive(name):
                yield
        except Busy:
            raise HTTPException(409, BUSY)

    def tmdb() -> Tmdb | None:
        """A token saved in Settings wins over the install's (.env); removing it in Settings brings that one back."""
        token = store.get("tmdb.token") or os.environ.get("TMDB_READ_TOKEN", "").strip()
        if not token:
            return None
        if tmdb_cache.get("token") != token:
            tmdb_cache.update(token=token, client=tmdb_factory(token, os.path.join(cfg.config_dir, "tmdb-cache.sqlite")))
        client = tmdb_cache["client"]
        client.language = store.get("tmdb.language") or "en-US"  # cached answers are kept per language
        return client

    def names() -> dict:
        """What the reader calls their NAS and the box Kodi runs on (Settings, Names); neutral until set."""
        return {"device": store.get("names.device") or "Kodi device", "nas": store.get("names.nas") or "NAS"}

    def download_station() -> DownloadStation | None:
        d = store.get("downloadstation", {})
        return DownloadStation(d["url"], d.get("user", ""), d.get("password", "")) if d.get("url") and d.get("user") else None

    def shield() -> Shield | None:
        """The box Kodi runs on, when waking it is set up in Settings."""
        sh, host = store.get("shield") or {}, (store.get("kodi") or {}).get("host")
        return (Shield(host, int(sh.get("port") or 5555), cfg.config_dir, device=names()["device"])
                if host and sh.get("enabled") and sh.get("app") else None)

    def wake_kodi() -> None:
        """Wake the box and start the chosen app until Kodi answers. Only for things the reader started."""
        sh = shield()
        if not sh:
            raise ShieldError(f"Waking the {names()['device']} isn't set up in Settings.")
        sh.wake_and_start((store.get("shield") or {})["app"], lambda: bool((k := kodi()) and k.check().get("connected")))

    def kodi_ready(timeout: float = 90) -> Kodi:
        """Kodi, answering: woken first when it sleeps and waking is set up. Otherwise a 409 that says why."""
        k = kodi(timeout)
        if not k:
            raise HTTPException(409, "Set up the Kodi connection in Settings first.")
        state = k.check()
        if state.get("connected"):
            return k
        if shield():
            try:
                wake_kodi()
                return k
            except ShieldError as e:
                raise HTTPException(409, f"Kodi doesn't answer, and waking the {names()['device']} didn't work: {e}")
        raise HTTPException(409, state.get("problem") or "Kodi doesn't answer.")

    def tell(message: str) -> None:
        """A short message on the TV when Kodi is on. Never wakes the box (ARCHITECTURE.md §11)."""
        k = kodi()
        if k:
            k.notify("muthur", message)

    def job_finished(job) -> None:
        """Told on the TV: a job the reader started that took more than half a minute (they may have walked
        away), anything that needs them, and any job that stopped with a problem. Quick ones stay quiet."""
        name = JOB_NAMES.get(job.name, job.name)
        if job.error:
            tell(f"{name} stopped with a problem. Details in muthur.")
        elif job.result and (job.attention or (job.by_user and (job.finished or 0) - job.started > 30)):
            tell(job.result)

    jobs.on_finish = job_finished

    def follow_watched(items) -> dict:
        """One watched-status backup; a backup that pauses (a library that looks wiped) is told once."""
        before = watched.state().get("paused")
        result = watched.follow(items)
        if result.get("paused") and not before:
            tell(f"Watched backup paused: {result['paused']['why']} Check it in muthur.")
        return result

    def not_dry():
        if store.get("dryRun", False):
            raise HTTPException(409, "Dry run is on: muthur only plans and changes nothing. Turn it off in Settings to make changes.")

    def kodi(timeout: float = 4) -> Kodi | None:
        k = store.get("kodi", {})
        if not k.get("host"):
            return None
        client = Kodi(k["host"], int(k.get("port") or 8080), k.get("user"), k.get("password"), timeout, device=names()["device"])
        client.on_away = remember_refresh
        return client

    def remember_refresh(paths: list[str]) -> None:
        """NFOs and artwork Kodi didn't hear about because it was off: it is told when it answers again (kodi_back).
        Until then it shows what it had, an old poster included."""
        store.put("kodi.pendingRefresh", list(dict.fromkeys((store.get("kodi.pendingRefresh") or []) + paths)))

    # -- signing in (§14) -------------------------------------------------------
    def signed_in(request: Request, response: Response) -> dict:
        response.set_cookie(COOKIE, auth.start_session(), max_age=SESSION_SECONDS, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/")
        return {"signedIn": True}

    def address(request: Request) -> str:
        return request.client.host if request.client else "?"

    @app.get("/api/auth")
    def auth_state(request: Request):
        return {"required": auth.required, "set": auth.is_set(),
                "signedIn": not auth.required or auth.valid(request.cookies.get(COOKIE))}

    @app.post("/api/auth/setup")
    def auth_setup(body: dict, request: Request, response: Response):
        """The first visit chooses the password; once one is set, this is refused."""
        if auth.is_set():
            raise HTTPException(409, "A password is already set. Sign in with it.")
        try:
            auth.set_password(str(body.get("password") or ""))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return signed_in(request, response)

    @app.post("/api/auth/login")
    def auth_login(body: dict, request: Request, response: Response):
        if not auth.allowed(address(request)):
            raise HTTPException(429, "Too many wrong passwords. Wait five minutes and try again.")
        if not auth.check(str(body.get("password") or "")):
            auth.failed(address(request))
            raise HTTPException(401, "That isn't the password.")
        return signed_in(request, response)

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response):
        auth.end_session(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"signedIn": False}

    @app.post("/api/auth/password")
    def auth_password(body: dict, request: Request, response: Response):
        """A new password signs every other browser out."""
        if not auth.allowed(address(request)):
            raise HTTPException(429, "Too many wrong passwords. Wait five minutes and try again.")
        if not auth.check(str(body.get("current") or "")):
            auth.failed(address(request))
            raise HTTPException(403, "The current password isn't right.")
        try:
            auth.set_password(str(body.get("new") or ""))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return signed_in(request, response)

    # -- status ---------------------------------------------------------------
    kodi_seen: dict = {}

    def kodi_state(k: Kodi) -> dict:
        """Kodi's answer for the status poll, reused for 20 s: a Shield that is off shouldn't slow every page."""
        if kodi_seen.get("url") != k.url or time.time() - kodi_seen.get("at", 0) > 20:
            state = k.check()
            if state.get("connected"):
                try:  # a video source in Kodi for each library folder (the setup checklist)
                    prefixes = {lib: k.source_prefix(folder_name(root)) for lib, root in (("TV", cfg.tv), ("Film", cfg.film))}
                    state["sources"] = {lib.lower(): bool(p) for lib, p in prefixes.items()}
                    if all(prefixes.values()) and store.get("player.sources") != prefixes:
                        store.put("player.sources", prefixes)  # the share, for the player's 'Open with', whenever Kodi answers
                except Exception:
                    pass
            kodi_seen.update(url=k.url, at=time.time(), state=state)
        return kodi_seen["state"]

    @app.get("/api/health", include_in_schema=False)
    def health():
        """For the container's health check and for deploying: 'busy' while a job runs or waits, so an update never
        restarts muthur in the middle of one (docs/DEPLOY.md)."""
        return {"ok": True, "busy": bool((jobs.current and jobs.current.running) or jobs.waiting())}

    @app.get("/api/status")
    def status():
        inbox, scanned = store.snapshot("inbox")
        counts = {}
        for it in inbox or []:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        k = kodi()
        return {
            "version": __version__,
            "names": names(),
            "applying": not store.get("dryRun", False),
            "tmdb": {"configured": tmdb() is not None},
            "kodi": {**kodi_state(k), "pendingScan": store.get("kodi.pendingScan"), "pendingRefresh": len(store.get("kodi.pendingRefresh") or []),
                     "canWake": shield() is not None} if k else None,
            "paths": {"downloads": _path_state(cfg.downloads), "tv": _path_state(cfg.tv), "film": _path_state(cfg.film)},
            "inbox": {"counts": counts, "scannedAt": scanned},
            "memory": {"shows": store.alias_count("tv")},
            "scores": scores_state(),
            "watched": {**watched.state(), "live": listener.connected},
            "duplicates": store.snapshot_count("duplicates", "$.groups"),
            "duplicateFilms": store.snapshot_count_kind("duplicates", "$.groups", "film"),  # the rest are episodes
            "duplicatesAt": store.snapshot_saved("duplicates"),  # None: never checked, so not 'none found'
            "fixes": store.snapshot_count("health", "$.fixes", each=True),
            "library": store.get("health.counts") or {},
            "job": jobs.current.as_dict() if jobs.current else None,
            "queue": [j.as_dict() for j in jobs.waiting()],
        }

    def scores_state() -> dict:
        info = imdb.refreshed()
        last, _ = store.snapshot("last-scores")
        return {"refreshed": info["at"] if info else None, "next": info["at"] + REFRESH_DAYS * 86400 if info else None,
                **imdb.counts(), "updated": (last or {}).get("updated"), "checked": (last or {}).get("checked")}

    # -- inbox ----------------------------------------------------------------
    @app.get("/api/inbox")
    def get_inbox():
        items, scanned = store.snapshot("inbox")
        return {"items": items or [], "scannedAt": scanned, "job": jobs.current.as_dict() if jobs.current else None}

    @app.post("/api/inbox/scan", status_code=202)
    def scan():
        client = tmdb()
        if client is None:
            raise HTTPException(409, "Add your TMDB token in Settings first.")
        if not os.path.isdir(cfg.downloads):
            raise HTTPException(409, "The downloads folder isn't reachable. Check the folder settings.")

        def work(job):
            items = Inbox(client, store, cfg.downloads, cfg.tv, cfg.film).scan(job)
            store.save_snapshot("inbox", [asdict(i) for i in items])
            ready, review = sum(i.status == "ready" for i in items), sum(i.status == "review" for i in items)
            job.result = f"Downloads checked: {ready} ready, {review} need you."

        job = jobs.start("inbox", work)
        return job.as_dict()

    # -- apply, history, undo --------------------------------------------------------
    def _rescan(client):
        store.save_snapshot("inbox", [asdict(i) for i in Inbox(client, store, cfg.downloads, cfg.tv, cfg.film).scan()])

    def _tell_kodi(wake: bool = False):
        """Ask Kodi to look for new files. wake: the reader started this, so a sleeping Shield may be woken.
        When Kodi stays asleep, the scan waits until it answers again."""
        k = kodi()
        if k and wake and shield() and not k.check().get("connected"):
            try:
                wake_kodi()
            except ShieldError:
                pass  # the scan waits instead
        if k:
            try:
                k.call("VideoLibrary.Scan")
                store.put("kodi.pendingScan", None)
            except Exception:  # Kodi being off must not fail the run: the listener catches up later
                store.put("kodi.pendingScan", time.time())

    def kodi_back():
        if store.get("kodi.pendingScan"):
            _tell_kodi()
        if store.get("kodi.pendingRefresh"):
            jobs.start("kodi-refresh", refresh_waiting, by_user=False)
        if renaming.pending(store):
            jobs.start("kodi-renames", finish_renames, by_user=False)

    def finish_renames(job):
        """Renamed files whose Kodi step a restart or a sleeping Kodi cut short: Kodi scans their folders, the new
        entries get the old ones' play count and resume point, the old entries go (rename.py)."""
        waiting = renaming.pending(store)
        k = kodi(timeout=30)
        if not waiting or not k or not k.check().get("connected"):
            return
        roots = {"TV": cfg.tv, "Film": cfg.film}
        job.begin("Reading what Kodi knows", 0)
        before = renaming.read_before(k, roots, follow_watched)  # Kodi kept the old entries, with their status
        job.begin(f"Kodi takes {count(len(waiting), 'new name')}", len(waiting))

        def took(old):
            renaming.forget(store, old)
            job.done += 1

        r = renaming.follow_in_kodi(k, waiting, roots, before, done=took)
        job.result = f"Kodi took {count(r['followed'], 'renamed file')} with {'its' if r['followed'] == 1 else 'their'} watched status" + (
            f"; {r['kodiAway']:,} wait for Kodi again." if r.get("kodiAway") else ".") + (
            f" {count(len(r['problems']), 'file')} Kodi didn’t list: their status is safe in muthur’s backup." if r["problems"] else "")
        job.attention = bool(r["problems"])

    def recover_interrupted():
        """At start-up: runs a restart cut short are closed in History, and the files they renamed still get their
        Kodi step (kodi_back), so no watched status stays behind."""
        for run in journal.unfinished():
            renamed = renaming.from_run(journal.ops(run["id"]), {"TV": cfg.tv, "Film": cfg.film}) if run["kind"] in ("health", "library") else []
            renaming.remember(store, renamed)
            journal.finish(run["id"], {"interrupted": True, "label": "Stopped by a restart; what it changed stays",
                                       "done": {}, "failed": [], "kodiWaiting": len(renamed)})

    def refresh_waiting(job):
        waiting = store.get("kodi.pendingRefresh") or []
        k = kodi(timeout=30)
        if not k or not waiting:
            return
        store.put("kodi.pendingRefresh", [])  # what Kodi misses again is remembered again (remember_refresh)
        job.total = len(waiting)
        r = k.refresh_files(waiting, {"TV": cfg.tv, "Film": cfg.film}, lambda d, t: setattr(job, "done", d))
        job.result = f"Kodi re-read {count(r['refreshed'], 'changed item')}" + (f"; {r['kodiAway']:,} wait for it again." if r.get("kodiAway") else ".")

    @app.post("/api/apply", status_code=202)
    def apply(body: dict | None = None):
        not_dry()
        client = tmdb()
        if client is None:
            raise HTTPException(409, "Add your TMDB token in Settings first.")
        items, _ = store.snapshot("inbox")
        asked = (body or {}).get("ids")
        if asked and (not isinstance(asked, list) or not {str(i) for i in asked} <= {i["id"] for i in items or []}):
            raise HTTPException(404, "A download isn't in the inbox any more. Check the downloads again.")
        wanted = {str(i) for i in asked} if asked else {i["id"] for i in items or [] if i["status"] == "ready"}
        if not wanted:
            raise HTTPException(409, "Nothing is ready to apply. Check the downloads first.")

        def work(job):
            inbox = Inbox(client, store, cfg.downloads, cfg.tv, cfg.film)
            # Look again right before acting: the plan must match what is on disk now.
            fresh = [asdict(inbox.examine(i)) for i in sorted(wanted)]
            result = Applier(client, journal, cfg.downloads, cfg.tv, cfg.film, cfg.quarantine, imdb).apply(fresh, job)
            ds = download_station()
            moved = {i["id"].rsplit("/", 1)[-1] for i in result["items"] if i["ok"]}
            if ds and moved:
                # Only now that the files are in the library: the finished tasks leave Download Station (§16).
                try:
                    result["downloadStation"] = ds.remove_finished(moved)
                except DownloadStationError as e:
                    result["downloadStation"] = {"problem": str(e)}
            store.save_snapshot("last-apply", result)
            job.result = f"{count(result['applied'], 'download')} filed" + (f", {result['stopped']} stopped." if result["stopped"] else ".")
            job.attention = bool(result["stopped"])
            _rescan(client)
            if result["applied"]:
                _tell_kodi(wake=True)

        job = jobs.start("apply", work)
        return job.as_dict()

    @app.get("/api/history")
    def history():
        runs = journal.runs()
        counts = journal.counts([r["id"] for r in runs])
        for r in runs:
            r["counts"] = {k: counts[r["id"]].get(k, 0) for k in ("move", "write", "quarantine", "mkdir", "update")}
        return {"runs": runs}

    @app.get("/api/history/{run_id}")
    def run_detail(run_id: int):
        return {"ops": journal.ops(run_id)}

    @app.post("/api/inbox/quarantine")
    def inbox_quarantine(body: dict):
        """A suspicious or packed download goes to quarantine (journalled, put back from History), so the reader
        doesn't need File Station for it. Emptying that day of the quarantine deletes it for good."""
        not_dry()
        item_id = str(body.get("id") or "")
        items, _ = store.snapshot("inbox")
        item = next((i for i in items or [] if i["id"] == item_id), None)
        if not item or item["status"] not in ("suspicious", "packed"):
            raise HTTPException(404, "Only a suspicious or packed download in the inbox can go to quarantine from here.")
        src = os.path.join(cfg.downloads, *item_id.split("/"))
        dst = os.path.join(cfg.quarantine, time.strftime("%Y-%m-%d"), "downloads", *item_id.split("/"))
        if os.path.lexists(dst):
            dst += f" ({int(time.time())})"
        why = ("A program named like an episode or film, taken out of the downloads." if item["status"] == "suspicious"
               else "A packed download, taken out of the downloads.")
        with alone("quarantine"):
            run = journal.start("inbox")
            try:
                journal.move(run, item_id, src, dst, "quarantine")
            except OSError as e:
                journal.finish(run, {"applied": 0, "stopped": 1, "items": [{"id": item_id, "ok": False, "why": str(e)}]})
                raise HTTPException(409, f"Couldn't move it: {getattr(e, 'strerror', None) or e}")
            quarantine_notes.note(cfg.quarantine, dst, item_id, run, why)
            journal.finish(run, {"applied": 1, "stopped": 0, "items": [{"id": item_id, "ok": True}],
                                 "label": f"{item_id} moved to quarantine"})
            store.save_snapshot("inbox", [i for i in items if i["id"] != item_id])
        return {"run": run}

    @app.post("/api/history/{run_id}/undo", status_code=202)
    def undo(run_id: int, body: dict | None = None):
        not_dry()  # putting back moves and deletes files too
        item = (body or {}).get("item")
        client = tmdb()

        def work(job):
            result = journal.undo(run_id, item)
            store.save_snapshot("last-undo", result)
            job.result = ("Put back." if not result["skipped"]
                          else f"Put back, but {count(len(result['skipped']), 'change')} couldn't be: see History.")
            job.attention = bool(result["skipped"])
            if client:
                _rescan(client)
            _tell_kodi(wake=True)

        job = jobs.start("undo", work)
        return job.as_dict()

    # -- ID memory --------------------------------------------------------------
    @app.post("/api/memory/import", status_code=202)
    def memory_import():
        client = tmdb()
        if client is None:
            raise HTTPException(409, "Add your TMDB token in Settings first.")

        def work(job):
            store.save_snapshot("memory", import_tv(client, cfg.tv, store, job))

        job = jobs.start("memory", work)
        return job.as_dict()

    # -- scores (IMDb) ----------------------------------------------------------
    def start_scores(by_user: bool = True):
        client = tmdb()
        if client is None:
            return None

        def work(job):
            refresh = ScoreRefresh(store, journal, imdb, client, cfg.tv, cfg.film, os.path.join(cfg.config_dir, "backups"), kodi())
            summary = refresh.run(job)
            store.save_snapshot("last-scores", summary)
            job.result = f"IMDb scores refreshed: {count(summary['updated'], 'NFO')} updated."

        return jobs.start("scores", work, by_user=by_user)

    @app.post("/api/scores/refresh", status_code=202)
    def scores_refresh():
        not_dry()
        if tmdb() is None:
            raise HTTPException(409, "Add your TMDB token in Settings first.")
        job = start_scores()
        return job.as_dict()

    # -- watched status (Kodi is the master; muthur keeps the history) -----------
    def kodi_items():
        k = kodi_ready()  # the whole library in one answer: give Kodi time
        try:
            return k, Watched.read_kodi(k)
        except Exception:
            state = k.check()
            raise HTTPException(409, state.get("problem") or "Kodi didn't answer in time. Try again in a minute.")

    @app.post("/api/watched/backup")
    def watched_backup():
        _, items = kodi_items()
        return watched.follow(items)

    @app.post("/api/watched/accept")
    def watched_accept():
        """The reader looked at a paused backup and says Kodi's current state is right."""
        _, items = kodi_items()
        return watched.follow(items, accept=True)

    @app.post("/api/watched/restore/preview")
    def restore_preview():
        _, items = kodi_items()
        plan = watched.plan_restore(items)
        return {"count": len(plan), "check": _plan_check(plan), "watched": sum(c["what"] == "watched" for c in plan),
                "resume": sum(c["what"] == "resume" for c in plan), "sample": [c["label"] for c in plan[:40]]}

    @app.post("/api/watched/restore")
    def restore(body: dict):
        """Writes to Kodi. Planned again right now; refused if it no longer matches what the reader saw."""
        k, items = kodi_items()
        plan = watched.plan_restore(items)
        if _plan_check(plan) != body.get("check"):  # the same changes the reader saw, not only as many
            raise HTTPException(409, "Kodi changed since the preview. Look at the preview again before restoring.")
        result = Watched.restore(k, plan)
        store.save_snapshot("last-restore", {**result, "at": time.time()})
        return result

    def scheduler():
        """Every hour: follow Kodi's watched status. Once a day: the Health check (read-only; it also builds
        the library index). Once a week: the IMDb scores. Fixes are never applied from here."""
        time.sleep(60)  # let a fresh start settle first
        if not outdated_check():
            time.sleep(240)  # sooner only when Health can't show the fixes an update added
        while True:
            try:
                k = kodi(timeout=90)
                if k and k.check().get("connected"):
                    follow_watched(Watched.read_kodi(k))
            except Exception:  # Kodi off or busy: the Dashboard shows when the last backup was
                pass
            try:
                client = tmdb()
                _, checked = store.snapshot("health")
                _, indexed = store.snapshot("library")
                # A day old, from before an update that added kinds of fixes, or older than muthur's last change to the
                # library (a run a restart cut short never got its own check): check again (read-only).
                if client and (not checked or time.time() - checked > 86400 or outdated_check() or checked < journal.last_change()):
                    jobs.start("health", lambda j, c=client: check_health(c, j), by_user=False)
                elif not client and (not indexed or time.time() - indexed > 86400):
                    start_library(by_user=False)  # without TMDB only the index can be built
            except Exception:
                pass
            try:
                if imdb.due() and not store.get("dryRun", False):  # the refresh rewrites NFOs: not in a dry run
                    start_scores(by_user=False)
            except Exception:  # never let the schedule die; the Dashboard shows when the last refresh was
                pass
            time.sleep(3600)

    def backup_now():
        k = kodi(timeout=90)
        if k:
            follow_watched(Watched.read_kodi(k))

    listener = Listener(lambda: (store.get("kodi") or {}).get("host"), backup_now, on_connect=kodi_back,
                        port=lambda: int((store.get("kodi") or {}).get("tcpPort") or 9090))
    recover_interrupted()  # before any job: an unfinished run now can only be one a restart cut short
    if cfg.scheduler:
        threading.Thread(target=scheduler, name="scheduler", daemon=True).start()
        threading.Thread(target=listener.run, name="kodi-listener", daemon=True).start()

    # -- library ------------------------------------------------------------------
    def start_library(by_user: bool = True):
        def work(job):
            store.save_snapshot("library", index.build(watched.latest(), job))

        return jobs.start("library", work, by_user=by_user)

    @app.post("/api/library/scan", status_code=202)
    def library_scan():
        job = start_library()
        return job.as_dict()

    @app.get("/api/library")
    def library():
        lib, _ = store.snapshot("library")
        if not lib:
            return {"at": None, "shows": [], "films": []}
        return {"at": lib["at"], "shows": [_show_summary(sh) for sh in lib["shows"]],
                "films": [_film_summary(f, n) for f, n in zip(lib["films"], _twins(lib["films"]), strict=True)]}

    @app.get("/api/library/show")
    def library_show(folder: str):
        lib, _ = store.snapshot("library")
        show = next((sh for sh in (lib or {}).get("shows", []) if sh["folder"] == folder), None)
        if not show:
            raise HTTPException(404, "That show isn't in the index. Index the library again.")
        dup = _duplicates(show["episodes"])
        names_now = episode_names(show)
        return {**_show_summary(show), "episodes": [{**e, "duplicate": _ep_key(e) in dup, "renameTo": names_now.get(e["file"])} for e in show["episodes"]],
                "loose": show["loose"], "scoreNotes": score_notes(show)}

    def season_titles(tmdb_id: int, season: int) -> dict[int, dict]:
        client = tmdb()
        try:
            return {x["episode_number"]: x for x in ((client.tv_season(tmdb_id, season) if client else None) or {}).get("episodes", [])}
        except Exception:
            return {}

    def episode_names(show: dict) -> dict[str, str]:
        """file -> the name the library gives it ('Show - S01E02 - TMDB's title.mkv'), where that differs: one
        numbered episode per file, and TMDB knows the episode."""
        tid = str(show["ids"].get("tmdb", ""))
        if not tid.isdigit():
            return {}
        titles: dict[int, dict] = {}
        out = {}
        group = (store.get("library.orders") or {}).get(show["folder"])
        order = health_tool(tmdb()).order_map(group) if group and tmdb() else None  # the show read by another TMDB order
        for e in show["episodes"]:
            if e["season"] is None or len(e["episodes"]) != 1 or e["damaged"]:
                continue
            if order is not None:
                title = (order.get((e["season"], e["episodes"][0])) or {}).get("name")
            else:
                if e["season"] not in titles:
                    titles[e["season"]] = season_titles(int(tid), e["season"])
                title = (titles[e["season"]].get(e["episodes"][0]) or {}).get("name")
            if title:
                name = renaming.new_name(show["folder"], e["file"], e["season"], e["episodes"], title)
                if name != e["file"].rsplit("/", 1)[-1]:
                    out[e["file"]] = name
        return out

    # -- one episode: the show page's menu ----------------------------------------
    def episode_at(path: str) -> tuple[dict, dict]:
        lib, _ = store.snapshot("library")
        lib_name, _, rest = path.partition("/")
        folder, _, file = rest.partition("/")
        show = next((s for s in (lib or {}).get("shows", []) if s["folder"] == folder), None) if lib_name == "TV" else None
        e = next((x for x in (show or {}).get("episodes", []) if x["file"] == file), None)
        if not show or not e or not os.path.isfile(os.path.join(cfg.tv, folder, *file.split("/"))):
            raise HTTPException(404, "That episode isn't in the index any more. Index the library again.")
        return show, e

    def episode_label(show: dict, s: int | None, n: int | None) -> str:
        return f"{show['title']} S{s:02d}E{n:02d}" if s is not None and n is not None else show["title"]

    @app.post("/api/library/episode/reread")
    def episode_reread(body: dict):
        path = str(body.get("path") or "")
        episode_at(path)
        k = kodi()
        if not k:
            raise HTTPException(409, "Kodi isn't set up in Settings.")
        nfo = os.path.join(cfg.tv, *path.partition("/")[2].rsplit(".", 1)[0].split("/")) + ".nfo"  # Kodi's entry is found by the name
        if not k.check().get("connected"):
            remember_refresh([nfo])
            return {"text": f"Kodi is off: it re-reads this episode when the {names()['device']} is on again."}
        r = k.refresh_files([nfo], {"TV": cfg.tv, "Film": cfg.film})
        return {"text": "Kodi re-read it." if r.get("refreshed") else "Kodi doesn’t have this episode yet; it adds it at its next scan."}

    @app.post("/api/library/episode/nfo")
    def episode_nfo(body: dict):
        path = str(body.get("path") or "")
        show, e = episode_at(path)
        client = need_tmdb()
        if e["nfo"]:
            raise HTTPException(409, "It has an NFO already.")
        if e["season"] is None or len(e["episodes"]) != 1:
            raise HTTPException(409, "muthur can’t tell which episode this is from its name. Use “It’s another episode”.")
        tool = health_tool(client)
        imdb_id, tmdb_id = tool.scores.show_ids(show["folder"])
        if not tmdb_id:
            raise HTTPException(409, "The show’s NFO has no TMDB ID. Change the show’s match first.")
        stem = path.rsplit(".", 1)[0]
        x = {"path": stem + ".nfo", "video": path, "tmdb": tmdb_id, "season": e["season"], "episode": e["episodes"][0], "show": show["title"],
             "imdbShow": imdb_id, "thumb": None if e["thumb"] else stem + "-thumb.jpg"}
        if (order := tool.show_order(show["folder"])) is not None:  # another order chosen: TMDB is asked by the aired numbers
            ep = order.get((e["season"], e["episodes"][0]))
            if not ep:
                raise HTTPException(409, "The order chosen for this show has no episode at this number.")
            x["aired"] = [ep["season_number"], ep["episode_number"]]
        label = episode_label(show, e["season"], e["episodes"][0])

        def work() -> dict:
            run = journal.start("library")
            tool._episode_nfos(run, x, [])
            journal.finish(run, {"label": f"NFO for {label}"})
            return {"run": run, "nfo": x["path"], "text": f"NFO written for {label}."}

        return edit(work)

    @app.post("/api/library/episode/rename", status_code=202)
    def episode_rename(body: dict):
        """Rename an episode to the library's naming. With season and episode: it is another episode than its name
        says, so it gets that number and title, and its NFO describes that episode. Kodi follows (rename.py)."""
        not_dry()
        client = need_tmdb()
        path = str(body.get("path") or "")
        show, e = episode_at(path)
        tid = str(show["ids"].get("tmdb", ""))
        if not tid.isdigit():
            raise HTTPException(409, "The show’s NFO has no TMDB ID. Change the show’s match first.")
        other = body.get("season") is not None
        try:
            s, n = (int(body["season"]), int(body["episode"])) if other else (e["season"], e["episodes"][0] if len(e["episodes"]) == 1 else None)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "Choose a season and an episode.")
        if s is None or n is None:
            raise HTTPException(409, "muthur can’t tell which episode this is from its name. Use “It’s another episode”.")
        ep = season_titles(int(tid), s).get(n)
        if not ep:
            raise HTTPException(409, f"TMDB has no S{s:02d}E{n:02d} for this show.")
        k = kodi(timeout=30)
        if not k:
            raise HTTPException(409, "Renaming needs Kodi, so the episode keeps its watched status. Set Kodi up in Settings.")
        label = episode_label(show, s, n)

        def work(job):
            if not k.check().get("connected"):
                job.begin(f"Waking the {names()['device']}", 0)
                try:
                    wake_kodi()
                except ShieldError:
                    pass
                if not k.check().get("connected"):
                    raise RuntimeError(f"Kodi is off, and renaming now would leave the watched status behind. Turn the {names()['device']} on and try again.")
            job.begin("Reading what Kodi knows", 0)
            roots = {"TV": cfg.tv}
            before = renaming.read_before(k, roots, follow_watched)  # muthur's watched backup is current before the rename
            new = renaming.new_name(show["folder"], e["file"], s, [n] if other else e["episodes"], ep.get("name"))
            run = journal.start("library")
            try:
                rel = f"{show['folder']}/{e['file']}"
                moved = renaming.rename(journal, run, cfg.tv, "TV", rel, f"{rel.rsplit('/', 1)[0]}/{new}")
            except (OSError, ValueError) as err:
                journal.undo(run)
                journal.finish(run, {"label": f"Rename of {label} stopped"})
                raise RuntimeError(f"Nothing was renamed: {getattr(err, 'strerror', None) or err}.")
            if other:  # the NFO describes the episode it really is
                nfo = os.path.join(cfg.tv, *moved.partition("/")[2].rsplit(".", 1)[0].split("/")) + ".nfo"
                imdb_id = health_tool(client).scores.show_ids(show["folder"])[0]
                data = nfo_write.episode_nfo(show["title"], s, ep, int(tid), imdb=imdb.episode(imdb_id, s, n, None) if imdb_id else None)
                if os.path.lexists(nfo):
                    journal.replace(run, moved, nfo, data, os.path.join(cfg.config_dir, "backups"))
                else:
                    journal.create(run, moved, nfo, data)
            job.begin("Kodi takes the new name", 0)
            renaming.remember(store, [(path, moved)])  # until Kodi took it, even across a restart
            followed = renaming.follow_in_kodi(k, [(path, moved)], roots, before, done=lambda old: renaming.forget(store, old))
            journal.finish(run, {"label": f"Renamed {label}", "kodi": followed})
            job.result = (f"Renamed {label} to {new}." + ("" if followed["followed"] else
                          f" Kodi didn’t take it all ({followed['problems'][0]['why'] if followed['problems'] else 'unknown'}); its watched status is safe"
                          " in muthur’s backup (Settings, Watched, Restore to Kodi)."))
            job.attention = not followed["followed"]
            start_library(by_user=False)

        if any(j.name == "rename" for j in [jobs.current, *jobs.waiting()] if j and (j.running or j.queued)):
            raise HTTPException(409, "Another episode is being renamed. Try again when it’s done.")  # jobs of one name merge
        job = jobs.start("rename", work)
        return job.as_dict()

    def score_notes(show: dict) -> dict[str, str]:
        """For each season with episodes lacking an IMDb score: why (DESIGN.md §8: a score left out says so)."""
        lacking = sorted({e["season"] for e in show["episodes"] if e["season"] is not None and not e["imdb"]})
        if not lacking:
            return {}
        imdb_id = show["ids"].get("imdb")
        if not imdb_id:
            return {str(s): "No IMDb scores: the show has no IMDb ID." for s in lacking}
        on_imdb = imdb.season_counts(imdb_id)
        if not on_imdb:
            if imdb_id in set(imdb.asked()):  # asked for in the last download, and still nothing: IMDb has no episodes for it
                return {str(s): "No IMDb scores: IMDb has no episodes for this show." for s in lacking}
            return {str(s): "No IMDb scores yet: they aren’t downloaded for this show. Health can download them." for s in lacking}
        on_tmdb: dict[int, int] = {}
        client = tmdb()
        if client and str(show["ids"].get("tmdb", "")).isdigit():
            try:
                on_tmdb = {x["season_number"]: x.get("episode_count") or 0 for x in (client.tv(int(show["ids"]["tmdb"])) or {}).get("seasons", [])}
            except Exception:
                pass
        notes = {}
        for s in lacking:
            ic, tc = on_imdb.get(s, 0), on_tmdb.get(s)
            notes[str(s)] = (f"IMDb has no episodes for season {s}." if not ic
                             else f"IMDb numbers season {s} differently ({ic} episodes on IMDb, {tc} on TMDB): its scores are left out."
                             if tc is not None and ic != tc else "IMDb has scores for this season: Health can add them to the NFOs.")
        return notes

    # -- library edits: match, title, poster (each one journalled run) -------------
    def editor() -> LibraryEdit:
        return LibraryEdit(store, journal, need_tmdb(), imdb, cfg.tv, cfg.film, os.path.join(cfg.config_dir, "backups"))

    def edited(result: dict) -> dict:
        """After an edit: Kodi re-reads the item if it answers, or as soon as it does; the index is built again."""
        k = kodi()
        if k and result.get("nfo"):
            full = editor().full(result["nfo"])
            if k.check().get("connected"):
                result["kodi"] = k.refresh_files([full], {"TV": cfg.tv, "Film": cfg.film})
            else:
                remember_refresh([full])
        start_library()
        return result

    def film_at(path: str) -> dict:
        lib, _ = store.snapshot("library")
        film = next((f for f in (lib or {}).get("films", []) if f.get("file") and f"Film/{f['file']}" == path), None)
        if not film:
            raise HTTPException(404, "That film isn't in the index. Index the library again.")
        return film

    def edit(fn):
        not_dry()
        with alone("edit"):
            try:
                result = fn()
            except (ValueError, OSError) as e:
                raise HTTPException(409, getattr(e, "strerror", None) or str(e))
        return edited(result)  # after the change: the index is built again as a job

    @app.post("/api/library/match")
    def library_match(body: dict):
        kind, path, tmdb_id = body.get("kind"), str(body.get("path") or ""), str(body.get("tmdbId") or "")
        if kind not in ("tv", "movie") or not tmdb_id.isdigit():
            raise HTTPException(422, "Choose a show or a film first.")
        if kind == "tv":
            folder = path.partition("/")[2]
            if not path.startswith("TV/") or "/" in folder:
                raise HTTPException(422, "Not a show folder.")
            return edit(lambda: editor().match_show(folder, int(tmdb_id)))
        f = film_at(path)
        prefix = f"{path.rsplit('/', 1)[0]}/" if f["folder"] else path.rsplit(".", 1)[0] + "-"  # artwork beside the video
        return edit(lambda: editor().match_film(path, f"Film/{f['nfoFile']}" if f.get("nfoFile") else None, prefix, int(tmdb_id)))

    @app.post("/api/library/title")
    def library_title(body: dict):
        return edit(lambda: editor().retitle(str(body.get("nfo") or ""), str(body.get("title") or "")))

    @app.get("/api/library/posters")
    def library_posters(kind: str, tmdbId: int):  # noqa: N803 (the query parameter's name)
        if kind not in ("tv", "movie"):
            raise HTTPException(422, "A show or a film.")
        return {"posters": editor().posters(kind, tmdbId)}

    @app.post("/api/library/poster")
    def library_poster(body: dict):
        target = str(body.get("target") or "")
        if not target.endswith(("poster.jpg", "-poster.jpg")):
            raise HTTPException(422, "Not a poster in the library.")
        return edit(lambda: editor().set_poster(target, str(body.get("image") or "")))

    ART_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".tbn": "image/jpeg"}

    @app.get("/api/library/art")
    def library_art(path: str):
        """An image from the library ('TV/Show/poster.jpg'), for the Library page. Nothing else is served."""
        lib_name, _, rest = path.partition("/")
        root = {"TV": cfg.tv, "Film": cfg.film}.get(lib_name)
        ext = os.path.splitext(rest)[1].lower()
        if not root or ext not in ART_TYPES:
            raise HTTPException(404, "Not an image in the library.")
        full = os.path.realpath(os.path.join(root, *rest.split("/")))
        if not full.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(full):
            raise HTTPException(404, "Not an image in the library.")
        return FileResponse(full, media_type=ART_TYPES[ext], headers={"Cache-Control": "no-cache"})

    # -- player (docs/PLAYER.md): read-only, the files are served as they are -------
    play_facts = player.Facts(store)
    sub_fit = subfit.SubFit(store)
    # Fix kinds only a whole Health check finds (Kodi's entries, subtitle files measured against their video): checking
    # one show again keeps them as they are.
    WHOLE_CHECK = {"kodi-entries", "subtitle-timing", "subtitle-misfit"}
    catalogue_cache: dict = {}
    VIDEO_TYPES = {".mkv": "video/x-matroska", ".webm": "video/webm", ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime"}

    def library_full(path: str) -> str:
        lib_name, _, rest = path.partition("/")
        return os.path.join({"TV": cfg.tv, "Film": cfg.film}[lib_name], *rest.split("/"))

    def play_of(path: str) -> str:
        return player.playback(play_facts.cached(library_full(path)))

    def player_video(vid: str) -> tuple[str, str]:
        """(library path, full path) of a video by its id; only videos the index knows."""
        lib, _ = store.snapshot("library")
        if not lib:
            raise HTTPException(404, "Index the library first.")
        if catalogue_cache.get("at") != lib["at"]:
            catalogue_cache.update(at=lib["at"], ids=player.catalogue(lib))
        path = catalogue_cache["ids"].get(vid)
        if not path or not os.path.isfile(full := library_full(path)):
            raise HTTPException(404, "That video isn't in the library any more.")
        return path, full

    @app.get("/api/player/items")
    def player_items():
        lib, _ = store.snapshot("library")
        return player.items(lib or {}, play_of)

    @app.get("/api/player/testset")
    def player_testset():
        """The trial's test set (docs/PLAYER.md §6): one real file per kind, kept as {kind: library path}."""
        out = []
        for what, path in (store.get("player.testSet") or {}).items():
            if not os.path.isfile(full := library_full(path)):
                continue
            stem, folder = path.rsplit(".", 1)[0], path.rsplit("/", 1)[0]
            art = next((p for p in (f"{folder}/poster.jpg", f"{stem}-poster.jpg", f"{stem}-thumb.jpg") if os.path.isfile(library_full(p))), None)
            out.append({"id": player.file_id(path), "kind": what, "name": os.path.basename(full), "path": path, "art": art,
                        "play": player.playback(play_facts.cached(full))})
        return {"items": out}

    @app.get("/api/player/show")
    def player_show(folder: str):
        lib, _ = store.snapshot("library")
        found = player.show(lib or {}, folder, play_of)
        if found is None:
            raise HTTPException(404, "That show isn't in the index.")
        return found

    @app.get("/api/player/video/{vid}/info")
    def player_info(vid: str):
        """What the player needs before it starts: how the video plays (the file is read now if it wasn't yet) and its subtitles."""
        path, full = player_video(vid)
        f = play_facts.get(full)
        original = original_language(path)
        inside = [name for _, name in player.to_extract(full, player.embedded(full))] if f and f.get("embeddedSubs") else []
        return {"id": vid, "path": path, "name": os.path.basename(full), "play": player.playback(f), "facts": f,
                "subtitles": player.sidecars(full), "original": original, "audio": player.audio_pick(f, original),
                "extractable": inside, "dryRun": bool(store.get("dryRun", False))}

    @app.post("/api/player/video/{vid}/subtitles/extract", status_code=202)
    def player_extract(vid: str):
        """Copy the video's text subtitles out as .srt beside it (decided 26 Oct): English, Dutch only without English.
        A journalled run, so History can put it back; the video itself is only read."""
        not_dry()
        path, full = player_video(vid)
        folder = path.rsplit("/", 1)[0]

        def work(job):
            chosen = player.to_extract(full, player.embedded(full))
            if not chosen:
                job.result = "No subtitles to copy out."
                return
            # done/total: thousandths of the file read so far, so the player shows how far the copy is
            job.begin(f"Copying {count(len(chosen), 'subtitle')} out of {os.path.basename(full)}", 1000)
            data = player.extract(full, chosen, os.path.join(cfg.config_dir, "tmp", "subtitles"),
                                  progress=lambda share: setattr(job, "done", int(share * 1000)))
            run = journal.start("subtitles")
            written = [name for name, body in data.items()
                       if journal.create(run, f"{folder}/{name}", os.path.join(os.path.dirname(full), name), body)]
            journal.finish(run, {"subtitles": written})
            job.result = f"{count(len(written), 'subtitle file')} written beside {os.path.basename(full)}."

        return jobs.start("subtitles-extract", work).as_dict()

    languages: dict[tuple, str | None] = {}

    def original_language(path: str) -> str | None:
        """The film's or show's original language from TMDB ('ja'), for the audio track to play; None when unknown."""
        lib, _ = store.snapshot("library")
        lib_name, _, rest = path.partition("/")
        if lib_name == "Film":
            owner = next((f for f in (lib or {}).get("films", []) if f.get("file") == rest), None)
        else:
            owner = next((s for s in (lib or {}).get("shows", []) if s["folder"] == rest.split("/", 1)[0]), None)
        client = tmdb()
        if not owner or not client:
            return None
        kind, ids = ("movie" if lib_name == "Film" else "tv"), owner["ids"]
        key = (kind, ids.get("tmdb"), ids.get("imdb"))
        if key not in languages:
            try:
                if str(ids.get("tmdb", "")).isdigit():
                    found = client.movie(int(ids["tmdb"])) if kind == "movie" else client.tv(int(ids["tmdb"]))
                elif ids.get("imdb"):
                    hits = client.find(ids["imdb"], "imdb_id")
                    found = (hits.get("movie_results" if kind == "movie" else "tv_results") or [{}])[0]
                else:
                    found = {}
                languages[key] = (found or {}).get("original_language") or None
            except Exception:  # TMDB unreachable: the file's default track plays
                return None
        return languages[key]

    @app.get("/api/player/video/{vid}")
    def player_file(vid: str, download: int = 0):
        """The video exactly as it is on disk, with Range requests (seeking); download=1 saves it under its own name."""
        _, full = player_video(vid)
        return FileResponse(full, media_type=VIDEO_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream"),
                            headers={"Cache-Control": "private, max-age=3600", "Referrer-Policy": "no-referrer"},
                            filename=os.path.basename(full) if download else None)

    def source_prefixes() -> dict:
        """Each library's place on the share as Kodi knows it ('smb://nas/share/TV/'), remembered from the last Health
        check; a library folder that is itself a share path (a local copy reading //nas/share/TV) stands for itself."""
        known = store.get("player.sources") or {}
        out = {}
        for lib_, root in (("TV", cfg.tv), ("Film", cfg.film)):
            unc = root.replace("\\", "/")
            out[lib_] = known.get(lib_) or ("smb:" + unc.rstrip("/") + "/" if unc.startswith("//") else None)
        return out

    @app.get("/api/player/video/{vid}/links")
    def player_links(vid: str):
        """For 'Open with': links a player outside the browser can open (a key instead of the sign-in, for 12 hours), the
        share path, and whether Kodi can play it on the TV."""
        path, full = player_video(vid)
        key = auth.link_key(vid)
        lib_name, _, rel = path.partition("/")
        return {"stream": f"/api/player/video/{vid}?key={key}",
                "subtitles": [{**s, "url": f"/api/player/video/{vid}/sidecar/{s['name']}?key={key}"} for s in player.sidecars(full)],
                "share": player.share_paths(source_prefixes().get(lib_name), rel), "tv": kodi() is not None,
                "name": os.path.basename(full)}

    @app.get("/api/player/video/{vid}/sidecar/{name}")
    def player_sidecar(vid: str, name: str, download: int = 0):
        """An .srt beside the video as it is (VLC and downloads want the file itself, not WebVTT)."""
        _, full = player_video(vid)
        if name not in {s["name"] for s in player.sidecars(full)}:
            raise HTTPException(404, "No such subtitle file beside the video.")
        return FileResponse(os.path.join(os.path.dirname(full), name), media_type="application/x-subrip",
                            filename=name if download else None, headers={"Referrer-Policy": "no-referrer"})

    @app.get("/api/player/video/{vid}/playlist.m3u")
    def player_playlist(request: Request, vid: str, windows: int = 0):
        """A one-line playlist for the PC's own player (VLC, mpv, MPC-HC, IINA): the share path, so the player finds the
        .srt beside the video itself (Windows gets the \\\\nas\\share path, other systems smb://). Before muthur learnt the
        share from Kodi: muthur's own link with a key (12 hours), which plays but leaves the .srt behind."""
        path, full = player_video(vid)
        lib_name, _, rel = path.partition("/")
        where = player.share_paths(source_prefixes().get(lib_name), rel)
        line = (where["unc"] if windows else where["smb"]) if where else f"{str(request.base_url).rstrip('/')}/api/player/video/{vid}?key={auth.link_key(vid)}"
        name = os.path.splitext(os.path.basename(full))[0]
        body = f"#EXTM3U\n#EXTINF:-1,{name}\n{line}\n"
        return Response(body, media_type="audio/x-mpegurl", headers={"Content-Disposition": f'attachment; filename="{_ascii(name)}.m3u"'})

    @app.post("/api/player/video/{vid}/tv")
    def player_tv(vid: str):
        """Kodi plays the video on the TV (Player.Open with its path in Kodi's source). When Kodi isn't running, the box
        is woken and Kodi started first, if waking is set up in Settings (the reader asked for it, 26 Oct)."""
        path, _ = player_video(vid)
        k = kodi_ready(timeout=10)
        lib_name, _, rel = path.partition("/")
        try:
            prefix = k.source_prefix(folder_name(cfg.tv if lib_name == "TV" else cfg.film))
            if not prefix:
                raise HTTPException(409, f"Kodi has no video source for the {lib_name} folder.")
            k.call("Player.Open", {"item": {"file": prefix + rel}})
        except HTTPException:
            raise
        except Exception:
            state = k.check()
            raise HTTPException(409, state.get("problem") or "Kodi didn't answer. Is the TV on?")
        return {"ok": True, "device": names()["device"]}

    @app.get("/api/player/zip")
    def player_zip(folder: str, season: int):
        """A season as one ZIP for a laptop: each episode as it is, with the .srt files beside it, made as it is sent."""
        lib, _ = store.snapshot("library")
        show = next((s for s in (lib or {}).get("shows", []) if s["folder"] == folder), None)
        if not show:
            raise HTTPException(404, "That show isn't in the index.")
        files = []
        for e in sorted(show["episodes"], key=lambda x: x["file"]):
            if e["season"] != season or e.get("sample"):
                continue
            full = library_full(f"TV/{folder}/{e['file']}")
            if os.path.isfile(full):
                files.append((os.path.basename(full), full))
                files += [(s["name"], os.path.join(os.path.dirname(full), s["name"])) for s in player.sidecars(full)]
        if not files:
            raise HTTPException(404, "No episodes of that season on disk.")
        title = f"{show['title']} - Season {season:02d}"
        return StreamingResponse(player.zip_stream([(f"{title}/{n}", p) for n, p in files]), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{_ascii(title)}.zip"'})

    @app.get("/api/player/video/{vid}/subtitles/{name}")
    def player_subtitles(vid: str, name: str):
        """One of the .srt files beside the video, as WebVTT (converted in memory; nothing is written)."""
        _, full = player_video(vid)
        if name not in {s["name"] for s in player.sidecars(full)}:
            raise HTTPException(404, "No such subtitle file beside the video.")
        with open(os.path.join(os.path.dirname(full), name), "rb") as fh:
            return Response(player.srt_to_vtt(fh.read()), media_type="text/vtt; charset=utf-8")

    @app.post("/api/player/scan", status_code=202)
    def player_scan():
        """Read how every video plays (ffprobe reads only the headers), so the player can mark what plays in Kodi only."""
        def work(job):
            lib, _ = store.snapshot("library")
            paths = list(player.catalogue(lib or {}).values())
            job.begin("Reading how each video plays", len(paths))
            for n, p in enumerate(paths, 1):
                play_facts.get(library_full(p))
                job.done = n
            job.result = f"{count(len(paths), 'video')} read."

        return jobs.start("player-scan", work).as_dict()

    # -- duplicates ---------------------------------------------------------------
    def find_duplicates(job):
        lib = index.build(watched.latest(), job)
        store.save_snapshot("library", lib)
        groups = dups.find(lib, job)
        store.save_snapshot("duplicates", {"at": time.time(), "groups": groups})
        job.result = f"Duplicates checked: {len(groups)} with more than one copy."

    @app.post("/api/duplicates/scan", status_code=202)
    def duplicates_scan():
        job = jobs.start("duplicates", find_duplicates)
        return job.as_dict()

    @app.get("/api/duplicates")
    def duplicates():
        data, _ = store.snapshot("duplicates")
        return data or {"at": None, "groups": []}

    def chosen_groups(choices: list[dict]) -> list[dict]:
        data, _ = store.snapshot("duplicates")
        by_id = {g["id"]: g for g in (data or {}).get("groups", [])}
        out = []
        for c in choices:
            g = by_id.get(str(c.get("id")))
            if not g:
                raise HTTPException(404, "A group isn't in the list any more. Check the duplicates again.")
            keep = c.get("keep") or g["keep"]
            if keep not in {x["path"] for x in g["copies"]}:
                raise HTTPException(422, "Choose one of the group's copies to keep.")
            out.append({**g, "keep": keep, "plan": dups.plan(g, keep) if keep != g["keep"] else g["plan"]})
        return out

    @app.post("/api/duplicates/plan")
    def duplicates_plan(body: dict):
        return chosen_groups([body])[0]["plan"]

    @app.post("/api/duplicates/apply", status_code=202)
    def duplicates_apply(body: dict):
        not_dry()
        groups = chosen_groups(body.get("choices") or [])
        if not groups:
            raise HTTPException(422, "Choose at least one group.")
        if not kodi():
            raise HTTPException(409, "Set up the Kodi connection first: muthur carries the watched status of every copy to the one it keeps.")
        try:
            k = kodi_ready()
        except HTTPException as e:
            raise HTTPException(409, f"{e.detail} muthur only resolves duplicates while Kodi answers, so watched status isn't lost.")

        def work(job):
            watched.follow(Watched.read_kodi(k))  # a fresh backup right before anything moves (§11)
            result = apply_groups(dups, groups, journal, cfg.quarantine, k, job)
            store.save_snapshot("last-duplicates", result)
            job.result = f"{count(result['applied'], 'duplicate')} resolved" + (f", {result['stopped']} stopped." if result["stopped"] else ".")
            job.attention = bool(result["stopped"])
            done = {r["id"] for r in result["items"] if r["ok"]}
            data, _ = store.snapshot("duplicates")
            if data:
                data["groups"] = [g for g in data["groups"] if g["id"] not in done]
                store.save_snapshot("duplicates", data)
            store.save_snapshot("library", index.build(watched.latest()))

        job = jobs.start("duplicates-apply", work)
        return job.as_dict()

    @app.get("/api/duplicates/last")
    def duplicates_last():
        data, _ = store.snapshot("last-duplicates")
        return data or {}

    # -- health: problems in the library and safe fixes --------------------------
    def health_tool(client) -> Health:
        return Health(store, journal, imdb, client, index, cfg.tv, cfg.film, cfg.quarantine, os.path.join(cfg.config_dir, "backups"))

    def health_counts(plan: dict) -> None:
        """What the Dashboard shows of the library's problems, kept small so the status poll stays cheap."""
        gone = store.get("health.left") or {}
        f = plan["fixes"]
        n = lambda *kinds: sum(len(f.get(k, [])) for k in kinds)  # noqa: E731
        store.put("health.counts", {
            # 'at' only for a check that knew every kind of fix: one from before an update isn't 'in order'.
            **({"at": plan.get("at")} if set(FIXES) <= set(f) else {}),
            "imdbData": n("imdb-data"), "scores": n("imdb-scores"), "nfos": n("episode-nfos", "show-nfos", "film-nfos"),
            "leftovers": n("leftovers", "empty-films"), "subtitles": n("subtitles"), "posters": n("posters"), "renames": n("renames", "film-renames"),
            "kodiEntries": n("kodi-entries"), "subTiming": n("subtitle-timing", "subtitle-misfit"),
            "questions": sum(1 for v in plan["manual"].values() for q in v if _question_key(q) not in gone)})

    def outdated_check() -> bool:
        """The last Health check was made by another version of muthur: its list may hold fixes this one makes
        differently (or not at all), or miss kinds it added. It is checked again soon after an update (read-only)."""
        plan, _ = store.snapshot("health")
        return bool(plan) and (not set(FIXES) <= set(plan["fixes"]) or plan.get("version") != __version__)

    def check_health(client, job):
        lib = index.build(watched.latest(), job)
        store.save_snapshot("library", lib)
        # What Kodi lists, for its old entries (Health's 'kodi-entries'); without Kodi that kind waits for the next check.
        items, prefixes = None, None
        k = kodi(timeout=90)  # the whole library in one answer
        try:
            if k and k.check().get("connected"):
                if job:
                    job.begin("Reading what Kodi lists", 0)
                items = Watched.read_kodi(k)
                prefixes = {lib_: k.source_prefix(folder_name(root)) for lib_, root in (("TV", cfg.tv), ("Film", cfg.film))}
                if all(prefixes.values()):
                    store.put("player.sources", prefixes)  # where the player's 'Open with' finds the share (docs/PLAYER.md)
                follow_watched(items)  # a watched backup comes free with it
        except Exception:  # Kodi went away: the rest of the check doesn't need it
            items, prefixes = None, None
        plan = health_tool(client).check(lib, job, items, prefixes)
        # Duplicates with it: an NFO written since the last look can make two copies the same film.
        if job:
            job.begin("Looking for duplicates", 0)
        store.save_snapshot("duplicates", {"at": time.time(), "groups": dups.find(lib, job)})
        # The player marks what plays in Kodi only from each video's codecs: read them for videos that are new since.
        new = [full for full in (library_full(p) for p in player.catalogue(lib).values()) if play_facts.cached(full) is None]
        if new and job:
            job.begin("Reading how new videos play", len(new))
        for n, full in enumerate(new, 1):
            play_facts.get(full)
            if job:
                job.done = n
        # Subtitle files beside a video that also has subtitles inside: do they fit it? (subfit; each measured once)
        plan["fixes"]["subtitle-timing"], plan["fixes"]["subtitle-misfit"] = [], []
        paths = [p for p in player.catalogue(lib).values() if (play_facts.cached(library_full(p)) or {}).get("embeddedSubs")]
        if paths and job:
            job.begin("Checking that subtitle files fit their video", len(paths))
        for n, path in enumerate(paths, 1):
            full = library_full(path)
            beside = player.sidecars(full)
            if beside:
                facts = play_facts.cached(full) or {}
                for r in sub_fit.check(full, facts.get("duration") or 0, beside, player.embedded(full)):
                    srt = f"{path.rsplit('/', 1)[0]}/{r['name']}"
                    if r["verdict"] == "stretch":
                        plan["fixes"]["subtitle-timing"].append({"path": srt, "shift": r["fit"]["shift"], "speed": r["fit"]["speed"],
                                                                 "why": subfit.describe(r["fit"])})
                    elif r["verdict"] == "cut":
                        plan["fixes"]["subtitle-misfit"].append({"path": srt, "why": "doesn't match the subtitles inside the video"})
            if job:
                job.done = n
        plan["version"] = __version__
        store.save_snapshot("health", plan)
        health_counts(plan)
        if job:
            job.result = (f"Library checked: {count(sum(len(v) for v in plan['fixes'].values()), 'fix', 'fixes')}, "
                          f"{count(sum(len(v) for v in plan['manual'].values()), 'question')}.")

    @app.post("/api/fixes/check", status_code=202)
    def fixes_check():
        client = need_tmdb()
        job = jobs.start("health", lambda j: check_health(client, j))
        return job.as_dict()

    @app.get("/api/fixes")
    def fixes(left: bool = False):
        """left: the questions the reader left as is, instead of the open ones."""
        plan, _ = store.snapshot("health")
        if not plan:
            return {"at": None, "fixes": {}, "manual": {}, "left": 0}
        gone = store.get("health.left") or {}
        manual = {k: [q for q in v if (_question_key(q) in gone) == left] for k, v in plan["manual"].items()}
        return {"at": plan["at"],
                "fixes": {k: {"count": len(v), "sample": v[:12]} for k, v in plan["fixes"].items()},
                "manual": {k: {"count": len(v), "items": v[:200]} for k, v in manual.items()},
                "left": sum(_question_key(q) in gone for v in plan["manual"].values() for q in v)}

    @app.post("/api/fixes/leave")
    def fixes_leave(body: dict):
        """The reader says a question is fine as it is: one question, or every question under a show or film
        ('under': 'TV/The Office (US)'). 'back': ask it again."""
        plan, _ = store.snapshot("health")
        if not plan:
            raise HTTPException(409, "Check the library first.")
        under = str(body.get("under") or "")
        wanted = {_question_key(q) for q in body.get("items") or [] if isinstance(q, dict) and q.get("path") and q.get("why")}
        if under:
            wanted |= {_question_key(q) for v in plan["manual"].values() for q in v
                       if q["path"] == under or q["path"].startswith(under + "/")}
        if not wanted:
            raise HTTPException(422, "Choose a question first.")
        gone = dict(store.get("health.left") or {})
        for key in wanted:
            if body.get("back"):
                gone.pop(key, None)
            else:
                gone[key] = time.time()
        store.put("health.left", gone)
        health_counts(plan)
        return {"changed": len(wanted)}

    @app.post("/api/fixes/apply", status_code=202)
    def fixes_apply(body: dict):
        not_dry()
        client = need_tmdb()
        kinds = [k for k in body.get("kinds") or [] if k in FIXES]
        plan, _ = store.snapshot("health")
        if not plan or not kinds:
            raise HTTPException(422, "Choose at least one kind of fix.")

        def work(job):
            k = kodi(timeout=30)
            if k and shield() and not k.check().get("connected"):
                try:
                    wake_kodi()  # the reader started this: Kodi should re-read what changed
                except ShieldError:
                    pass  # the fixes still happen; Kodi re-reads the items later
            extra = {}
            if "imdb-data" in kinds:
                # The download covers every show in the library; muthur's own NFOs get their scores right away.
                job.begin(f"Downloading IMDb scores for {len(plan['fixes'].get('imdb-data', [])):,} shows", 0)
                summary = ScoreRefresh(store, journal, imdb, client, cfg.tv, cfg.film, os.path.join(cfg.config_dir, "backups"), k).run(job)
                store.save_snapshot("last-scores", summary)
                extra["imdb-data"] = len(plan["fixes"].get("imdb-data", []))
            rest = [x for x in kinds if x != "imdb-data"]
            result = health_tool(client).apply(plan, rest, k, job, backup=follow_watched) if rest else {"run": None, "done": {}, "failed": []}
            result["done"].update(extra)
            store.save_snapshot("last-fixes", result)
            job.begin("Checking the library again", 0)
            check_health(client, job)
            failed = len(result["failed"])
            lost = len((result.get("kodiRenames") or {}).get("problems", []))
            job.result = f"{count(sum(result['done'].values()), 'fix', 'fixes')} done" + (f", {failed} couldn't be: see Health." if failed else ".") + (
                f" Kodi didn’t take {count(lost, 'renamed item')}: their watched status is safe in muthur’s backup (Settings, Watched, Restore to Kodi)."
                if lost else "")
            job.attention = bool(failed or lost)

        job = jobs.start("fixes-apply", work)
        return job.as_dict()

    @app.post("/api/fixes/choose")
    def fixes_choose(body: dict):
        """The reader says which show or film a library folder is. A show is remembered for its folder; a
        film's choice is kept for its file. That one item is checked again right away."""
        client = need_tmdb()
        with alone("edit"):
            return choose_in_library(client, body)

    def choose_in_library(client, body: dict) -> dict:
        kind, path, tmdb_id = body.get("kind"), str(body.get("path") or ""), str(body.get("tmdbId") or "")
        if kind not in ("tv", "movie") or not tmdb_id.isdigit():
            raise HTTPException(422, "Choose a show or a film first.")
        plan, _ = store.snapshot("health")
        lib, _ = store.snapshot("library")
        if not plan or not lib:
            raise HTTPException(409, "Check the library first.")
        tool = health_tool(client)
        fixes_new: dict = {k: [] for k in FIXES}
        manual_new: dict = {k: [] for k in plan["manual"]}
        if kind == "tv":
            folder = path.partition("/")[2]
            show = next((s for s in lib["shows"] if s["folder"] == folder), None)
            d = client.tv(int(tmdb_id)) or {}
            if not show or not d.get("id"):
                raise HTTPException(404, "That show isn't in the index, or not on TMDB.")
            year = _year(d.get("first_air_date"))
            for name in {parse_show_folder(folder).title, d.get("name")}:
                if name:
                    store.remember("tv", name, int(tmdb_id), year, d.get("name") or name, folder, "confirmed")
            return replan_show(client, folder)
        else:
            film = next((f for f in lib["films"] if f.get("file") and f"Film/{f['file']}" == path), None)
            d = client.movie(int(tmdb_id)) or {}
            if not film or not d.get("id"):
                raise HTTPException(404, "That film isn't in the index, or not on TMDB.")
            year = _year(d.get("release_date"))
            choices = store.get("library.films") or {}
            choices[path] = {"tmdbId": int(tmdb_id), "label": f"{d.get('title')} ({year})" if year else d.get("title")}
            store.put("library.films", choices)
            tool._film(film, fixes_new, manual_new)
            return merge_plan(plan, lambda x: x["path"] == path or x.get("video") == path, fixes_new, manual_new)

    def merge_plan(plan: dict, mine, fixes_new: dict, manual_new: dict) -> dict:
        """One show or film checked again: its old fixes and questions make way for the new ones."""
        for k in (set(plan["fixes"]) | set(fixes_new)) - WHOLE_CHECK:
            plan["fixes"][k] = [x for x in plan["fixes"].get(k, []) if not mine(x)] + fixes_new.get(k, [])
        for k in plan["manual"]:
            plan["manual"][k] = [x for x in plan["manual"][k] if not mine(x)] + manual_new.get(k, [])
        store.save_snapshot("health", plan)
        health_counts(plan)
        return {"fixes": {k: len(v) for k, v in fixes_new.items() if v}, "questions": sum(len(v) for v in manual_new.values())}

    def replan_show(client, folder: str) -> dict:
        """Check one show folder again (after the reader answered a question about it) and update the plan."""
        plan, _ = store.snapshot("health")
        lib, _ = store.snapshot("library")
        show = next((s for s in (lib or {}).get("shows", []) if s["folder"] == folder), None)
        if not plan or not show:
            raise HTTPException(409, "Check the library first.")
        fixes_new: dict = {k: [] for k in FIXES}
        manual_new: dict = {k: [] for k in plan["manual"]}
        health_tool(client)._show(show, fixes_new, manual_new)
        return merge_plan(plan, lambda x: x["path"] == f"TV/{folder}" or x["path"].startswith(f"TV/{folder}/"), fixes_new, manual_new)

    ORDER_TYPES = {1: "Original air date", 2: "Absolute", 3: "DVD", 4: "Digital", 5: "Story arc", 6: "Production", 7: "TV"}

    @app.get("/api/library/orders")
    def library_orders(folder: str):
        """TMDB's other orders for a show ('episode groups': DVD, production…), each with how many of the library's
        episode files it has a place for, so the reader picks the one that matches the files."""
        client = need_tmdb()
        lib, _ = store.snapshot("library")
        show = next((s for s in (lib or {}).get("shows", []) if s["folder"] == folder), None)
        if not show:
            raise HTTPException(404, "That show isn't in the index. Index the library again.")
        tool = health_tool(client)
        tmdb_id = tool.scores.show_ids(folder)[1]
        if not tmdb_id:
            raise HTTPException(409, "The show’s NFO has no TMDB ID. Change the show’s match first.")
        files = [(e["season"], e["episodes"][0]) for e in show["episodes"] if e["season"] is not None and e["episodes"]]
        out = []
        for g in (client.get(f"/tv/{tmdb_id}/episode_groups", max_age=7 * 86400) or {}).get("results", []):
            mapping = tool.order_map(g["id"])
            out.append({"id": g["id"], "name": g.get("name"), "kind": ORDER_TYPES.get(g.get("type"), "Other"),
                        "seasons": g.get("group_count") or 0, "episodes": g.get("episode_count") or 0,
                        "fits": sum(1 for f in files if f in mapping)})
        out.sort(key=lambda o: -o["fits"])
        return {"orders": out, "files": len(files), "current": (store.get("library.orders") or {}).get(folder)}

    @app.post("/api/library/order")
    def library_order(body: dict):
        """Read a show by another TMDB order (or, with no group, by TMDB's own again); the show is checked again."""
        client = need_tmdb()
        folder, group = str(body.get("folder") or ""), body.get("groupId")
        orders = dict(store.get("library.orders") or {})
        if group:
            orders[folder] = str(group)
        else:
            orders.pop(folder, None)
        with alone("edit"):
            store.put("library.orders", orders)
            return replan_show(client, folder)

    @app.post("/api/fixes/trust")
    def fixes_trust(body: dict):
        """'The number is right': the reader confirms an episode's own number. muthur then writes its NFO and score
        (and can name it) like any episode it is sure about. The show is checked again right away."""
        client = need_tmdb()
        path = str(body.get("path") or "")
        if not path.startswith("TV/") or path.count("/") < 2:
            raise HTTPException(422, "That isn't an episode in the library.")
        with alone("edit"):
            store.put("health.trusted", sorted(set(store.get("health.trusted") or []) | {path}))
            return replan_show(client, path.split("/")[1])

    @app.get("/api/fixes/last")
    def fixes_last():
        data, _ = store.snapshot("last-fixes")
        return data or {}

    # -- quarantine ---------------------------------------------------------------
    DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    @app.get("/api/quarantine")
    def quarantine():
        """What is in quarantine, per day it was put there."""
        days = []
        if os.path.isdir(cfg.quarantine):
            for d in sorted(os.listdir(cfg.quarantine)):
                path = os.path.join(cfg.quarantine, d)
                if DAY.match(d) and os.path.isdir(path):
                    files = [os.path.join(dp, n) for dp, _, names in os.walk(path) for n in names if n != quarantine_notes.NOTES]
                    days.append({"day": d, "files": len(files), "size": sum(os.path.getsize(f) for f in files if os.path.isfile(f))})
        return {"days": days}

    @app.get("/api/quarantine/{day}")
    def quarantine_day(day: str):
        if not DAY.match(day):
            raise HTTPException(404, "Not a day in the quarantine.")
        return {"notes": quarantine_notes.notes(cfg.quarantine, day)}

    @app.post("/api/quarantine/empty")
    def quarantine_empty(body: dict):
        """Deletes the chosen days for good. Only ever on the reader's explicit confirmation in the page."""
        not_dry()
        days = [d for d in body.get("days") or [] if isinstance(d, str) and DAY.match(d)]
        if not days or body.get("confirm") != "delete":
            raise HTTPException(422, "Choose the days to empty, and confirm.")
        freed = 0
        with alone("quarantine"):
            for d in days:
                path = os.path.join(cfg.quarantine, d)
                if os.path.isdir(path):
                    freed += _size(path)
                    shutil.rmtree(path)
        return {"emptied": days, "freed": freed}

    @app.get("/api/jobs/current")
    def current_job():
        return jobs.current.as_dict() if jobs.current else None

    # -- review -----------------------------------------------------------------
    def need_tmdb() -> Tmdb:
        client = tmdb()
        if client is None:
            raise HTTPException(409, "Add your TMDB token in Settings first.")
        return client

    def inbox_items(item_id: str) -> list[dict]:
        items, _ = store.snapshot("inbox")
        if not any(i["id"] == item_id for i in items or []):
            raise HTTPException(404, "That download isn't in the inbox any more. Check the downloads again.")
        return items

    def examine(client, item_id: str, choice: dict | None = None) -> dict:
        try:
            return asdict(Inbox(client, store, cfg.downloads, cfg.tv, cfg.film).examine(item_id, choice))
        except OSError as e:
            raise HTTPException(409, f"Couldn't read the download: {e.strerror or e}")

    def replace(items: list[dict], new: dict) -> None:
        store.save_snapshot("inbox", [new if i["id"] == new["id"] else i for i in items])

    @app.get("/api/tmdb/search")
    def tmdb_search(kind: str, q: str, year: int | None = None):
        client = need_tmdb()
        if kind not in ("tv", "movie"):
            raise HTTPException(422, "Search for a show or a film.")
        if not q.strip():
            raise HTTPException(422, "Type a title to search for.")
        found = client.search_tv(q.strip(), year) if kind == "tv" else client.search_movie(q.strip(), year)
        return {"results": [_card(kind, r) for r in found[:12]]}

    @app.post("/api/tmdb/resolve")
    def tmdb_resolve(body: dict):
        """A pasted themoviedb.org or imdb.com link (or a bare IMDb tt-number) as a card."""
        client = need_tmdb()
        link = str(body.get("link") or "").strip()
        if m := TMDB_LINK.search(link):
            kind, tmdb_id = m.group(1), int(m.group(2))
            d = client.tv(tmdb_id) if kind == "tv" else client.movie(tmdb_id)
            if not (d or {}).get("id"):
                raise HTTPException(404, "TMDB has no title at that link.")
            return _card(kind, d)
        if m := IMDB_ID.search(link):
            found = client.find(m.group(1), "imdb_id") or {}
            if found.get("tv_results"):
                return _card("tv", found["tv_results"][0])
            if found.get("movie_results"):
                return _card("movie", found["movie_results"][0])
            if found.get("tv_episode_results"):  # a link to one episode: the show it belongs to
                return _card("tv", client.tv(found["tv_episode_results"][0]["show_id"]))
            raise HTTPException(404, "TMDB doesn't know that IMDb title.")
        raise HTTPException(422, "Paste a link to a title on themoviedb.org or imdb.com.")

    @app.get("/api/tmdb/tv/{tv_id}/season/{season}")
    def tmdb_season(tv_id: int, season: int):
        client = need_tmdb()
        d = client.tv(tv_id) or {}
        data = client.tv_season(tv_id, season) or {}
        return {
            "seasons": [{"season": x["season_number"], "name": x.get("name"), "episodes": x.get("episode_count") or 0}
                        for x in d.get("seasons", [])],
            "episodes": [{"episode": e["episode_number"], "title": e.get("name"), "aired": e.get("air_date"),
                          "runtime": e.get("runtime"), "overview": e.get("overview"), "still": e.get("still_path")}
                         for e in data.get("episodes", [])],
        }

    @app.post("/api/review/preview")
    def review_preview(body: dict):
        """What a choice would do, without keeping it."""
        client = need_tmdb()
        item_id, choice = _choice(body)
        inbox_items(item_id)
        return examine(client, item_id, choice)

    @app.post("/api/review/choose")
    def review_choose(body: dict):
        client = need_tmdb()
        item_id, choice = _choice(body)
        with alone("review"):
            items = inbox_items(item_id)
            new = examine(client, item_id, choice)
            store.choose(item_id, choice)
            title = new["parsed"].get("title")
            if body.get("remember") and choice["kind"] == "tv" and title:
                # 'Remember for this show': the next download with this name goes straight to this show.
                store.remember("tv", title, choice["tmdbId"], new["year"], new["title"], store.folder_for("tv", choice["tmdbId"]), "confirmed")
            replace(items, new)
        return new

    @app.post("/api/review/forget")
    def review_forget(body: dict):
        """Drop a choice: the item is planned again as if it had never been reviewed."""
        client = need_tmdb()
        item_id = str(body.get("id") or "")
        with alone("review"):
            items = inbox_items(item_id)
            store.forget_choice(item_id)
            new = examine(client, item_id)
            replace(items, new)
        return new

    # -- settings ---------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        k = store.get("kodi", {})
        ds = store.get("downloadstation", {})
        return {
            "kodi": {"host": k.get("host", ""), "port": k.get("port", 8080), "tcpPort": k.get("tcpPort", 9090),
                     "user": k.get("user", ""), "passwordSet": bool(k.get("password"))},
            "tmdb": {"tokenSet": tmdb() is not None,
                     "tokenFrom": "settings" if store.get("tmdb.token") else "install" if os.environ.get("TMDB_READ_TOKEN", "").strip() else None,
                     "language": store.get("tmdb.language") or "en-US"},
            "titles": {"keepOriginal": store.get("titles.keepOriginal", sorted(LATIN_SCRIPT))},
            "downloadStation": {"url": ds.get("url", ""), "user": ds.get("user", ""), "passwordSet": bool(ds.get("password"))},
            "openSubtitles": {"user": (store.get("opensubtitles") or {}).get("user", ""),
                              "apiKeySet": bool((store.get("opensubtitles") or {}).get("apiKey")),
                              "passwordSet": bool((store.get("opensubtitles") or {}).get("password"))},
            "dryRun": bool(store.get("dryRun", False)),
            "shield": {"enabled": bool((store.get("shield") or {}).get("enabled")), "port": int((store.get("shield") or {}).get("port") or 5555),
                       "app": (store.get("shield") or {}).get("app") or ""},
            "quality": {"preferHdr": bool(store.get("quality.preferHdr", False))},
            "names": names(),
            "paths": {"downloads": cfg.downloads, "tv": cfg.tv, "film": cfg.film},
        }

    @app.put("/api/settings")
    def put_settings(body: dict):
        if "kodi" in body:
            k = dict(store.get("kodi", {}))
            new = body["kodi"]
            if "host" in new and str(new["host"]).strip() != k.get("host", ""):
                k.pop("password", None)  # a stored password only ever goes to the address it was given for
            for key in ("host", "user"):
                if key in new:
                    k[key] = str(new[key]).strip()
            for key, example in (("port", 8080), ("tcpPort", 9090)):
                if key in new:
                    try:
                        k[key] = int(new[key])
                    except (TypeError, ValueError):
                        raise HTTPException(422, f"The port must be a number, for example {example}.")
            if new.get("password"):
                k["password"] = new["password"]
            store.put("kodi", k)
        if isinstance(body.get("shield"), dict):
            sh, new = dict(store.get("shield") or {}), body["shield"]
            if isinstance(new.get("enabled"), bool):
                sh["enabled"] = new["enabled"]
            if "port" in new:
                try:
                    sh["port"] = int(new["port"])
                except (TypeError, ValueError):
                    raise HTTPException(422, "The ADB port must be a number; network debugging uses 5555 unless you changed it.")
            if "app" in new:
                component = str(new["app"]).strip()
                if component and not COMPONENT.match(component):
                    raise HTTPException(422, f"Choose the app from the list the {names()['device']} gives.")
                sh["app"] = component
            store.put("shield", sh)
        for key, value in (body.get("names") or {}).items():
            if key in ("device", "nas"):
                store.put(f"names.{key}", str(value).strip()[:40])  # empty: back to the neutral name
        if isinstance(body.get("dryRun"), bool):
            store.put("dryRun", body["dryRun"])
        if isinstance((body.get("quality") or {}).get("preferHdr"), bool):
            store.put("quality.preferHdr", body["quality"]["preferHdr"])
        if "downloadStation" in body:
            d = {} if body["downloadStation"].get("forget") else dict(store.get("downloadstation", {}))
            new = body["downloadStation"]
            if "url" in new and str(new["url"]).strip() != d.get("url", ""):
                d.pop("password", None)  # as for Kodi: never send the password to a new address
            for key in ("url", "user"):
                if key in new:
                    d[key] = str(new[key]).strip()
            if new.get("password"):
                d["password"] = new["password"]
            store.put("downloadstation", d)
        if isinstance(body.get("openSubtitles"), dict):
            new = body["openSubtitles"]
            o = {} if new.get("forget") else dict(store.get("opensubtitles") or {})
            if "user" in new and str(new["user"]).strip() != o.get("user", ""):
                o.pop("password", None)  # a password only ever goes with the account it was typed for
            if "user" in new:
                o["user"] = str(new["user"]).strip()
            for key in ("apiKey", "password"):
                if new.get(key):
                    o[key] = str(new[key]).strip() if key == "apiKey" else new[key]
            store.put("opensubtitles", o)
            store.put("opensubtitles.session", None)
        t = body.get("tmdb") or {}
        if t.get("forget"):
            store.put("tmdb.token", None)
        elif (token := t.get("token")):
            store.put("tmdb.token", token.strip())
        if "language" in t:
            if not TMDB_LANGUAGE.match(str(t["language"])):
                raise HTTPException(422, "Choose a language from the list.")
            store.put("tmdb.language", t["language"])
        if "titles" in body and isinstance(body["titles"].get("keepOriginal"), list):
            store.put("titles.keepOriginal", sorted({str(c) for c in body["titles"]["keepOriginal"]}))
        return get_settings()

    def opensubtitles() -> OpenSubtitles:
        o = store.get("opensubtitles") or {}
        if not (o.get("apiKey") and o.get("user") and o.get("password")):
            raise HTTPException(409, "Add your OpenSubtitles.com API key and account in Settings first.")
        return OpenSubtitles(o["apiKey"], o["user"], o["password"], store)

    @app.post("/api/opensubtitles/test")
    def opensubtitles_test():
        return opensubtitles().check()

    def subtitle_target(path: str) -> tuple[str, dict]:
        """A library video's full path, and what OpenSubtitles is searched by: the film's IMDb ID, or the show's with
        the episode's season and number."""
        lib_name = path.partition("/")[0]
        if lib_name == "TV":
            show, e = episode_at(path)
            if e["season"] is None or len(e["episodes"]) != 1:
                raise HTTPException(409, "muthur can’t tell which episode this is. Use “It’s another episode” first.")
            imdb_id = health_tool(need_tmdb()).scores.show_ids(show["folder"])[0] if tmdb() else show["ids"].get("imdb")
            return (os.path.join(cfg.tv, show["folder"], *e["file"].split("/")),
                    {"parent_imdb_id": imdb_id or show["ids"].get("imdb"), "season": e["season"], "episode": e["episodes"][0]})
        if lib_name == "Film":
            film = film_at(path)
            return os.path.join(cfg.film, *film["file"].split("/")), {"imdb_id": film["ids"].get("imdb")}
        raise HTTPException(404, "That isn’t a video in the library.")

    @app.get("/api/library/subtitles")
    def library_subtitles(path: str):
        """Subtitles on OpenSubtitles for one video, with what helps choose; English first, Dutch when English is thin."""
        video, ids = subtitle_target(path)
        try:
            results = opensubtitles().search(video=video, **ids)
        except OpenSubtitlesError as e:
            raise HTTPException(409, str(e))
        session = store.get("opensubtitles.session") or {}
        return {"file": os.path.basename(video), "results": results[:40], "count": len(results), "allowed": session.get("allowed")}

    @app.post("/api/library/subtitles")
    def library_subtitle_save(body: dict):
        """The subtitle the reader chose, saved beside the video as '<video>.en.srt' (or .nl), where Kodi finds it.
        Never over an existing file: a second English one becomes '<video>.2.en.srt'. Journalled, so History can take
        it away again."""
        not_dry()
        path = str(body.get("path") or "")
        language = re.sub(r"[^a-z]", "", str(body.get("language") or "en").lower())[:3] or "en"
        try:
            file_id = int(body.get("fileId"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise HTTPException(422, "Choose a subtitle first.")
        video, _ = subtitle_target(path)
        try:
            data, remaining = opensubtitles().download(file_id)
        except OpenSubtitlesError as e:
            raise HTTPException(409, str(e))
        stem, k = os.path.splitext(video)[0], 2
        target = f"{stem}.{language}.srt"
        while os.path.lexists(target):
            target, k = f"{stem}.{k}.{language}.srt", k + 1
        with alone("edit"):
            run = journal.start("library")
            journal.create(run, path, target, data)
            journal.finish(run, {"label": f"Subtitle for {path.rsplit('/', 1)[-1]}"})
        start_library(by_user=False)  # the show page lists the new language
        return {"saved": os.path.basename(target), "remaining": remaining}

    @app.post("/api/downloadstation/test")
    def downloadstation_test():
        ds = download_station()
        return ds.check() if ds else {"connected": False, "problem": "Enter the NAS address and the account first."}

    @app.get("/api/shield/apps")
    def shield_apps():
        """The apps the Shield can start, and the one on screen now (connecting asks the TV once to allow muthur)."""
        host = (store.get("kodi") or {}).get("host")
        if not host:
            raise HTTPException(409, f"Enter the {names()['device']}'s address under Kodi first.")
        sh = Shield(host, int((store.get("shield") or {}).get("port") or 5555), cfg.config_dir, device=names()["device"])
        try:
            sh.connect()
            return {"apps": sh.apps(), "current": sh.current_app()}
        except ShieldError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/shield/wake")
    def shield_wake():
        k = kodi()
        if k and k.check().get("connected"):
            return {"ok": True, "woke": False, "note": "Kodi already answers."}
        try:
            wake_kodi()
        except ShieldError as e:
            raise HTTPException(409, str(e))
        kodi_back()  # a scan that waited for Kodi runs now
        kodi_seen.clear()
        return {"ok": True, "woke": True}

    @app.post("/api/kodi/test")
    def kodi_test():
        k = kodi()
        kodi_seen.clear()
        return k.check() if k else {"connected": False, "problem": f"Enter the {names()['device']}'s address first."}

    @app.post("/api/kodi/scan")
    def kodi_scan():
        """Ask Kodi to look for new files in its video sources (it reads the NFOs muthur wrote)."""
        k = kodi()
        if not k:
            raise HTTPException(409, "Set up the Kodi connection in Settings first.")
        state = k.check()
        if not state.get("connected"):
            raise HTTPException(409, state.get("problem", "Kodi isn't reachable."))
        k.call("VideoLibrary.Scan")
        return {"started": True}

    # -- the UI -----------------------------------------------------------------
    dist = Path(cfg.web_dist)
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    store.migrate()  # every module has created its tables by now
    app.state.store, app.state.jobs, app.state.started = store, jobs, time.time()
    app.state.kodi_back = kodi_back  # what the listener runs when Kodi answers again (tests call it directly)
    return app


app = None


def get_app() -> FastAPI:
    """uvicorn entry point: `uvicorn muthur.web:get_app --factory`."""
    return create_app()
