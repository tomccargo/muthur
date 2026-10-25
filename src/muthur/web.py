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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__
from .auth import COOKIE, SESSION_SECONDS, Auth, same_site
from .config import load_dotenv
from .apply import Applier
from .imdb import REFRESH_DAYS, Imdb
from .downloadstation import DownloadStation, DownloadStationError
from .duplicates import Duplicates, apply_groups
from .health import FIXES, Health
from .inbox import Inbox
from .library_edit import LibraryEdit
from .index import Index
from .jobs import Busy, Jobs
from .journal import Journal
from .kodi import Kodi
from .memory import import_tv
from .naming import LATIN_SCRIPT
from .parse import parse_show_folder
from . import quarantine as quarantine_notes
from .scores import ScoreRefresh
from .shield import COMPONENT, Shield, ShieldError
from .store import Store
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
    app = FastAPI(title="muthur", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    tmdb_cache: dict = {}
    auth = Auth(store, cfg.auth)
    OPEN = {"/api/health", "/api/auth", "/api/auth/login", "/api/auth/setup", "/api/auth/logout"}
    BUSY = "Another job is running. Try again when it's done."

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Every API request: a change a browser says comes from another site is refused, and only a
        signed-in browser gets an answer (§14)."""
        path = request.url.path
        if path.startswith("/api/"):
            if request.method not in ("GET", "HEAD", "OPTIONS") and not same_site(request.headers):
                return JSONResponse({"detail": "Refused: this request came from another website."}, status_code=403)
            if auth.required and path not in OPEN and not await run_in_threadpool(auth.valid, request.cookies.get(COOKIE)):
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

    def not_dry():
        if store.get("dryRun", False):
            raise HTTPException(409, "Dry run is on: muthur only plans and changes nothing. Turn it off in Settings to make changes.")

    def kodi(timeout: float = 4) -> Kodi | None:
        k = store.get("kodi", {})
        return Kodi(k["host"], int(k.get("port") or 8080), k.get("user"), k.get("password"), timeout,
                    device=names()["device"]) if k.get("host") else None

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
            kodi_seen.update(url=k.url, at=time.time(), state=k.check())
        return kodi_seen["state"]

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"ok": True}

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
            "kodi": {**kodi_state(k), "pendingScan": store.get("kodi.pendingScan"), "canWake": shield() is not None} if k else None,
            "paths": {"downloads": _path_state(cfg.downloads), "tv": _path_state(cfg.tv), "film": _path_state(cfg.film)},
            "inbox": {"counts": counts, "scannedAt": scanned},
            "memory": {"shows": store.alias_count("tv")},
            "scores": scores_state(),
            "watched": {**watched.state(), "live": listener.connected},
            "duplicates": store.snapshot_count("duplicates", "$.groups"),
            "fixes": store.snapshot_count("health", "$.fixes", each=True),
            "job": jobs.current.as_dict() if jobs.current else None,
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

        job = jobs.start("inbox", work)
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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
            _rescan(client)
            if result["applied"]:
                _tell_kodi(wake=True)

        job = jobs.start("apply", work)
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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

    @app.post("/api/history/{run_id}/undo", status_code=202)
    def undo(run_id: int, body: dict | None = None):
        not_dry()  # putting back moves and deletes files too
        item = (body or {}).get("item")
        client = tmdb()

        def work(job):
            store.save_snapshot("last-undo", journal.undo(run_id, item))
            if client:
                _rescan(client)
            _tell_kodi(wake=True)

        job = jobs.start("undo", work)
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
        return job.as_dict()

    # -- scores (IMDb) ----------------------------------------------------------
    def start_scores():
        client = tmdb()
        if client is None:
            return None

        def work(job):
            refresh = ScoreRefresh(store, journal, imdb, client, cfg.tv, cfg.film, os.path.join(cfg.config_dir, "backups"), kodi())
            store.save_snapshot("last-scores", refresh.run(job))

        return jobs.start("scores", work)

    @app.post("/api/scores/refresh", status_code=202)
    def scores_refresh():
        not_dry()
        if tmdb() is None:
            raise HTTPException(409, "Add your TMDB token in Settings first.")
        job = start_scores()
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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
        time.sleep(300)  # let a fresh start settle first
        while True:
            try:
                k = kodi(timeout=90)
                if k and k.check().get("connected"):
                    watched.follow(Watched.read_kodi(k))
            except Exception:  # Kodi off or busy: the Dashboard shows when the last backup was
                pass
            try:
                client = tmdb()
                _, checked = store.snapshot("health")
                _, indexed = store.snapshot("library")
                if client and (not checked or time.time() - checked > 86400):  # a day old: check again
                    jobs.start("health", lambda j, c=client: check_health(c, j))
                elif not client and (not indexed or time.time() - indexed > 86400):
                    start_library()  # without TMDB only the index can be built
            except Exception:
                pass
            try:
                if imdb.due() and not store.get("dryRun", False):  # the refresh rewrites NFOs: not in a dry run
                    start_scores()
            except Exception:  # never let the schedule die; the Dashboard shows when the last refresh was
                pass
            time.sleep(3600)

    def backup_now():
        k = kodi(timeout=90)
        if k:
            watched.follow(Watched.read_kodi(k))

    listener = Listener(lambda: (store.get("kodi") or {}).get("host"), backup_now, on_connect=kodi_back,
                        port=lambda: int((store.get("kodi") or {}).get("tcpPort") or 9090))
    if cfg.scheduler:
        threading.Thread(target=scheduler, name="scheduler", daemon=True).start()
        threading.Thread(target=listener.run, name="kodi-listener", daemon=True).start()

    # -- library ------------------------------------------------------------------
    def start_library():
        def work(job):
            store.save_snapshot("library", index.build(watched.latest(), job))

        return jobs.start("library", work)

    @app.post("/api/library/scan", status_code=202)
    def library_scan():
        job = start_library()
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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
        return {**_show_summary(show), "episodes": [{**e, "duplicate": _ep_key(e) in dup} for e in show["episodes"]], "loose": show["loose"]}

    # -- library edits: match, title, poster (each one journalled run) -------------
    def editor() -> LibraryEdit:
        return LibraryEdit(store, journal, need_tmdb(), imdb, cfg.tv, cfg.film, os.path.join(cfg.config_dir, "backups"))

    def edited(result: dict) -> dict:
        """After an edit: Kodi re-reads the item if it answers, and the index is built again."""
        k = kodi()
        if k and result.get("nfo") and k.check().get("connected"):
            result["kodi"] = k.refresh_files([editor().full(result["nfo"])], {"TV": cfg.tv, "Film": cfg.film})
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
        return FileResponse(full, media_type=ART_TYPES[ext], headers={"Cache-Control": "max-age=3600"})

    # -- duplicates ---------------------------------------------------------------
    def find_duplicates(job):
        lib = index.build(watched.latest(), job)
        store.save_snapshot("library", lib)
        store.save_snapshot("duplicates", {"at": time.time(), "groups": dups.find(lib, job)})

    @app.post("/api/duplicates/scan", status_code=202)
    def duplicates_scan():
        job = jobs.start("duplicates", find_duplicates)
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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
            done = {r["id"] for r in result["items"] if r["ok"]}
            data, _ = store.snapshot("duplicates")
            if data:
                data["groups"] = [g for g in data["groups"] if g["id"] not in done]
                store.save_snapshot("duplicates", data)
            store.save_snapshot("library", index.build(watched.latest()))

        job = jobs.start("duplicates-apply", work)
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
        return job.as_dict()

    @app.get("/api/duplicates/last")
    def duplicates_last():
        data, _ = store.snapshot("last-duplicates")
        return data or {}

    # -- health: problems in the library and safe fixes --------------------------
    def health_tool(client) -> Health:
        return Health(store, journal, imdb, client, index, cfg.tv, cfg.film, cfg.quarantine, os.path.join(cfg.config_dir, "backups"))

    def check_health(client, job):
        lib = index.build(watched.latest(), job)
        store.save_snapshot("library", lib)
        store.save_snapshot("health", health_tool(client).check(lib, job))

    @app.post("/api/fixes/check", status_code=202)
    def fixes_check():
        client = need_tmdb()
        job = jobs.start("health", lambda j: check_health(client, j))
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
        return job.as_dict()

    @app.get("/api/fixes")
    def fixes():
        plan, _ = store.snapshot("health")
        if not plan:
            return {"at": None, "fixes": {}, "manual": {}}
        return {"at": plan["at"],
                "fixes": {k: {"count": len(v), "sample": v[:12]} for k, v in plan["fixes"].items()},
                "manual": {k: {"count": len(v), "items": v[:200]} for k, v in plan["manual"].items()}}

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
            result = health_tool(client).apply(plan, kinds, k, job)
            store.save_snapshot("last-fixes", result)
            job.begin("Checking the library again", 0)
            check_health(client, job)

        job = jobs.start("fixes-apply", work)
        if job is None:
            raise HTTPException(409, "Another job is running. Try again when it's done.")
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
            tool._show(show, fixes_new, manual_new)
            mine = lambda x: x["path"] == f"TV/{folder}" or x["path"].startswith(f"TV/{folder}/")  # noqa: E731
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
            mine = lambda x: x["path"] == path or x.get("video") == path  # noqa: E731
        for k in plan["fixes"]:
            plan["fixes"][k] = [x for x in plan["fixes"][k] if not mine(x)] + fixes_new.get(k, [])
        for k in plan["manual"]:
            plan["manual"][k] = [x for x in plan["manual"][k] if not mine(x)] + manual_new.get(k, [])
        store.save_snapshot("health", plan)
        return {"fixes": {k: len(v) for k, v in fixes_new.items() if v}, "questions": sum(len(v) for v in manual_new.values())}

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
    return app


app = None


def get_app() -> FastAPI:
    """uvicorn entry point: `uvicorn muthur.web:get_app --factory`."""
    return create_app()
