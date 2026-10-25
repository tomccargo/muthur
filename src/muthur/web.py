"""The FastAPI app: a small JSON API plus the built React UI. One process, one worker."""
from __future__ import annotations

import os
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import load_dotenv
from .inbox import Inbox
from .jobs import Jobs
from .kodi import Kodi
from .memory import import_tv
from .naming import LATIN_SCRIPT
from .store import Store
from .tmdb import Tmdb


class Config:
    """Paths from the environment; the defaults match compose.yaml on the NAS."""

    def __init__(self, dotenv: bool = True):
        if dotenv:
            load_dotenv()
        self.config_dir = os.environ.get("MUTHUR_CONFIG", "/config")
        self.downloads = os.environ.get("MUTHUR_DOWNLOADS", "/data/torrent-output/complete")
        self.tv = os.environ.get("MUTHUR_TV", "/data/TV")
        self.film = os.environ.get("MUTHUR_FILM", "/data/Film")
        self.web_dist = os.environ.get("MUTHUR_WEB", str(Path(__file__).resolve().parents[2] / "web" / "dist"))


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
    jobs = Jobs()
    app = FastAPI(title="muthur", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    tmdb_cache: dict = {}

    def tmdb() -> Tmdb | None:
        token = store.get("tmdb.token") or os.environ.get("TMDB_READ_TOKEN", "").strip()
        if not token:
            return None
        if tmdb_cache.get("token") != token:
            tmdb_cache.update(token=token, client=tmdb_factory(token, os.path.join(cfg.config_dir, "tmdb-cache.sqlite")))
        return tmdb_cache["client"]

    def kodi() -> Kodi | None:
        k = store.get("kodi", {})
        return Kodi(k["host"], int(k.get("port") or 8080), k.get("user"), k.get("password")) if k.get("host") else None

    # -- status ---------------------------------------------------------------
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
            "applying": False,  # milestone 2: muthur only plans; nothing is moved yet
            "tmdb": {"configured": tmdb() is not None},
            "kodi": k.check() if k else None,
            "paths": {"downloads": _path_state(cfg.downloads), "tv": _path_state(cfg.tv), "film": _path_state(cfg.film)},
            "inbox": {"counts": counts, "scannedAt": scanned},
            "memory": {"shows": store.alias_count("tv")},
            "job": jobs.current.as_dict() if jobs.current else None,
        }

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

    @app.get("/api/jobs/current")
    def current_job():
        return jobs.current.as_dict() if jobs.current else None

    # -- settings ---------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        k = store.get("kodi", {})
        return {
            "kodi": {"host": k.get("host", ""), "port": k.get("port", 8080), "user": k.get("user", ""),
                     "passwordSet": bool(k.get("password"))},
            "tmdb": {"tokenSet": tmdb() is not None},
            "titles": {"keepOriginal": store.get("titles.keepOriginal", sorted(LATIN_SCRIPT))},
            "paths": {"downloads": cfg.downloads, "tv": cfg.tv, "film": cfg.film},
        }

    @app.put("/api/settings")
    def put_settings(body: dict):
        if "kodi" in body:
            k = dict(store.get("kodi", {}))
            new = body["kodi"]
            for key in ("host", "user"):
                if key in new:
                    k[key] = str(new[key]).strip()
            if "port" in new:
                try:
                    k["port"] = int(new["port"])
                except (TypeError, ValueError):
                    raise HTTPException(422, "The port must be a number, for example 8080.")
            if new.get("password"):
                k["password"] = new["password"]
            store.put("kodi", k)
        if (token := (body.get("tmdb") or {}).get("token")):
            store.put("tmdb.token", token.strip())
        if "titles" in body and isinstance(body["titles"].get("keepOriginal"), list):
            store.put("titles.keepOriginal", sorted({str(c) for c in body["titles"]["keepOriginal"]}))
        return get_settings()

    @app.post("/api/kodi/test")
    def kodi_test():
        k = kodi()
        return k.check() if k else {"connected": False, "problem": "Enter the Shield's address first."}

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

    app.state.store, app.state.jobs, app.state.started = store, jobs, time.time()
    return app


app = None


def get_app() -> FastAPI:
    """uvicorn entry point: `uvicorn muthur.web:get_app --factory`."""
    return create_app()
