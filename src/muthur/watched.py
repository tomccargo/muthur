"""Watched-status backup: Kodi is the master, muthur keeps a history that follows it (ARCHITECTURE.md §11).

Each poll reads play count, last played and resume point of every episode and film from Kodi
and appends a row for each item whose state changed. Items are keyed by what they are (show ID,
season, episode; film ID), not by path, so a rename or a new Kodi database doesn't lose them.

muthur writes to Kodi only on an explicit Restore, after a preview, and a restore only raises
play counts and fills in missing resume points.
"""
from __future__ import annotations

import json
import time

from .text import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS watched (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,            -- 'ep:tmdb:2316:4:19', 'movie:imdb:tt0069293', ...
    kind TEXT NOT NULL,           -- episode | movie
    label TEXT NOT NULL,          -- for the reader: 'The Office S04E19', 'Solaris (1972)'
    ids TEXT NOT NULL,            -- JSON: every ID Kodi knew for the show or film
    season INTEGER,
    episode INTEGER,
    playcount INTEGER NOT NULL,
    lastplayed TEXT,
    resume REAL NOT NULL,         -- seconds; 0 = no resume point
    total REAL NOT NULL,
    file TEXT,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS watched_by_key ON watched (key, id);
"""

GUARD_UNWATCHED = 25  # more items than this turning unwatched in one poll: stop following
GUARD_SHRINK = 0.8  # Kodi's library below this share of the last poll: stop following
ID_ORDER = ("tmdb", "imdb", "tvdb")


def _ids(uniqueid: dict | None) -> dict:
    return {k: str(v) for k, v in (uniqueid or {}).items() if v and k in ID_ORDER}


def _key(prefix: str, ids: dict, fallback: str) -> str:
    for kind in ID_ORDER:
        if ids.get(kind):
            return f"{prefix}:{kind}:{ids[kind]}"
    return f"{prefix}:title:{normalize(fallback)}"


def _code(s, e) -> str:
    return f"S{int(s):02d}E{int(e):02d}"


class Watched:
    def __init__(self, store):
        self.store = store
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()

    # -- reading Kodi ---------------------------------------------------------------------
    @staticmethod
    def read_kodi(kodi) -> list[dict]:
        """Every episode and film in Kodi with its watched state, keyed by identity."""
        shows = {s["tvshowid"]: s for s in (kodi.call("VideoLibrary.GetTVShows", {"properties": ["title", "year", "uniqueid"]}) or {}).get("tvshows", [])}
        eps = (kodi.call("VideoLibrary.GetEpisodes", {"properties": [
            "tvshowid", "season", "episode", "playcount", "lastplayed", "resume", "file", "showtitle"]}) or {}).get("episodes", [])
        movies = (kodi.call("VideoLibrary.GetMovies", {"properties": [
            "title", "year", "uniqueid", "playcount", "lastplayed", "resume", "file"]}) or {}).get("movies", [])
        items = []
        for e in eps:
            show = shows.get(e.get("tvshowid"), {})
            ids = _ids(show.get("uniqueid"))
            title = show.get("title") or e.get("showtitle") or ""
            items.append({"key": f"{_key('ep', ids, title)}:{e['season']}:{e['episode']}", "kind": "episode",
                          "label": f"{title} {_code(e['season'], e['episode'])}", "ids": ids, "season": e["season"],
                          "episode": e["episode"], "kodiid": e["episodeid"], **_state(e)})
        for m in movies:
            ids = _ids(m.get("uniqueid"))
            label = f"{m.get('title', '')} ({m['year']})" if m.get("year") else m.get("title", "")
            items.append({"key": _key("movie", ids, label), "kind": "movie", "label": label, "ids": ids,
                          "season": None, "episode": None, "kodiid": m["movieid"], **_state(m)})
        return items

    # -- following Kodi -------------------------------------------------------------------
    def latest(self) -> dict[str, dict]:
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT w.* FROM watched w JOIN (SELECT key, MAX(id) AS id FROM watched GROUP BY key) l ON w.id = l.id").fetchall()
        return {r["key"]: dict(r) for r in rows}

    def follow(self, items: list[dict], accept: bool = False) -> dict:
        """Append the changes in `items` (one Kodi poll). Stops instead when the poll looks like a
        wiped or replaced database, unless the reader accepted Kodi's state (accept=True)."""
        known = self.latest()
        last = self.store.get("watched.last") or {}
        merged = _merged(items)
        unwatched = [k for k, i in merged.items() if i["playcount"] == 0 and known.get(k, {}).get("playcount", 0) > 0]
        # Counted as the reader counts them (two copies of one episode are one item), like watched.last.
        shrunk = bool(last.get("items")) and len(merged) < last["items"] * GUARD_SHRINK
        if not accept and (len(unwatched) > GUARD_UNWATCHED or shrunk):
            why = (f"Kodi's library has {len(merged)} items, down from {last['items']}." if shrunk
                   else f"{len(unwatched)} items would turn unwatched at once.")
            paused = {"at": time.time(), "why": why, "unwatched": len(unwatched), "items": len(merged)}
            self.store.put("watched.paused", paused)
            return {"paused": paused}
        now, rows = time.time(), []
        for i in merged.values():
            k = known.get(i["key"])
            if k and (k["playcount"], k["lastplayed"], round(k["resume"]), round(k["total"])) == (
                    i["playcount"], i["lastplayed"], round(i["resume"]), round(i["total"])):
                continue
            rows.append((i["key"], i["kind"], i["label"], json.dumps(i["ids"]), i["season"], i["episode"],
                         i["playcount"], i["lastplayed"], i["resume"], i["total"], i["file"], now))
        with self.store.lock:
            self.store.db.executemany("INSERT INTO watched (key, kind, label, ids, season, episode, playcount, lastplayed, "
                                      "resume, total, file, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self.store.db.commit()
        watched = sum(1 for i in merged.values() if i["playcount"] > 0)
        state = {"at": now, "items": len(merged), "watched": watched, "changes": len(rows)}
        self.store.put("watched.last", state)
        self.store.put("watched.paused", None)
        return state

    def state(self) -> dict:
        return {"last": self.store.get("watched.last"), "paused": self.store.get("watched.paused")}

    # -- restore --------------------------------------------------------------------------
    def plan_restore(self, items: list[dict]) -> list[dict]:
        """What a restore would change in Kodi now: play counts raised to the backup's, and resume
        points filled in where Kodi has none. Never lowers anything."""
        backup = self.latest()
        by_ids: dict[str, dict] = {}
        for b in backup.values():  # a second way in: any shared ID, for items Kodi now keys differently
            for kind, v in json.loads(b["ids"]).items():
                by_ids[_alt_key(b["kind"], kind, v, b["season"], b["episode"])] = b
        now = _merged(items)  # two copies of one episode count as one: either copy having it is enough
        changes = []
        for i in items:
            b = backup.get(i["key"]) or next((by_ids[a] for kind, v in i["ids"].items()
                                              if (a := _alt_key(i["kind"], kind, v, i["season"], i["episode"])) in by_ids), None)
            if not b:
                continue
            have = now[i["key"]]
            if b["playcount"] > have["playcount"]:
                changes.append({**_target(i), "playcount": b["playcount"], "lastplayed": b["lastplayed"] or i["lastplayed"],
                                "was": i["playcount"], "what": "watched"})
            elif have["playcount"] == 0 and b["resume"] > 0 and have["resume"] == 0:
                changes.append({**_target(i), "resume": b["resume"], "total": b["total"], "what": "resume"})
        return changes

    @staticmethod
    def restore(kodi, changes: list[dict]) -> dict:
        done = failed = 0
        for c in changes:
            method, key = ("VideoLibrary.SetEpisodeDetails", "episodeid") if c["kind"] == "episode" else ("VideoLibrary.SetMovieDetails", "movieid")
            params = {key: c["kodiid"]}
            if c["what"] == "watched":
                params.update(playcount=c["playcount"], **({"lastplayed": c["lastplayed"]} if c["lastplayed"] else {}))
            else:
                params["resume"] = {"position": c["resume"], "total": c["total"]}
            try:
                kodi.call(method, params)
                done += 1
            except Exception:
                failed += 1
        return {"done": done, "failed": failed}


def _merged(items: list[dict]) -> dict[str, dict]:
    """One state per identity. Two files of the same episode or film (a second copy, a
    multi-part film) are one item to the reader: the most-watched state of the copies wins."""
    out: dict[str, dict] = {}
    for i in items:
        o = out.get(i["key"])
        if o is None:
            out[i["key"]] = dict(i)
            continue
        o["playcount"] = max(o["playcount"], i["playcount"])
        o["lastplayed"] = max(filter(None, (o["lastplayed"], i["lastplayed"])), default=None)
        if i["resume"] > o["resume"]:
            o["resume"], o["total"] = i["resume"], i["total"]
    return out


def _alt_key(kind: str, id_kind: str, value: str, season, episode) -> str:
    return f"{kind}:{id_kind}:{value}:{season}:{episode}"


def _target(i: dict) -> dict:
    return {"kind": i["kind"], "kodiid": i["kodiid"], "label": i["label"]}


def _state(x: dict) -> dict:
    resume = x.get("resume") or {}
    return {"playcount": int(x.get("playcount") or 0), "lastplayed": x.get("lastplayed") or None,
            "resume": float(resume.get("position") or 0), "total": float(resume.get("total") or 0), "file": x.get("file")}


class Listener:
    """Kodi's notifications over its TCP JSON-RPC port (9090, 'Allow remote control from applications on
    other systems'). When something is watched, stopped or changed, a backup runs once Kodi has been quiet
    for `settle` seconds; the hourly poll stays as the safety net. Reconnects by itself."""

    TRIGGERS = {"VideoLibrary.OnUpdate", "Player.OnStop", "VideoLibrary.OnRemove", "VideoLibrary.OnScanFinished"}

    def __init__(self, address, backup, settle: float = 30, port: int = 9090, on_connect=None):
        """address() -> the Shield's host or None (settings can change); backup() runs one backup;
        on_connect() runs each time Kodi answers again (after the Shield slept), for work that waited."""
        self.address, self.backup, self.settle, self.port, self.on_connect = address, backup, settle, port, on_connect
        self.last_event: float | None = None
        self.connected = False

    def run(self) -> None:
        import socket
        import threading

        threading.Thread(target=self._debounce, name="watched-debounce", daemon=True).start()
        wait = 5
        while True:
            host = self.address()
            if not host:
                time.sleep(60)
                continue
            try:
                with socket.create_connection((host, self.port), timeout=10) as conn:
                    conn.settimeout(600)  # Kodi is silent while nothing happens; a timeout just reconnects
                    self.connected, wait = True, 5
                    self.last_event = time.time()  # things may have changed while Kodi was away: back up soon
                    if self.on_connect:
                        try:
                            self.on_connect()
                        except Exception:
                            pass
                    self._read(conn)
            except OSError:
                pass
            self.connected = False
            time.sleep(wait)
            wait = min(wait * 2, 300)

    def _read(self, conn) -> None:
        decoder, buffer = json.JSONDecoder(), ""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buffer += chunk.decode("utf-8", errors="replace")
            while buffer:
                buffer = buffer.lstrip()
                try:
                    msg, end = decoder.raw_decode(buffer)
                except ValueError:
                    if not buffer.startswith("{") or len(buffer) > 1 << 20:
                        buffer = buffer[buffer.find("{", 1):] if "{" in buffer[1:] else ""  # not JSON: skip to the next message
                        continue
                    break  # an incomplete message: wait for the rest
                buffer = buffer[end:]
                if isinstance(msg, dict) and msg.get("method") in self.TRIGGERS:
                    self.last_event = time.time()

    def _debounce(self) -> None:
        while True:
            time.sleep(5)
            if self.last_event and time.time() - self.last_event >= self.settle:
                self.last_event = None
                try:
                    self.backup()
                except Exception:
                    pass  # Kodi busy or gone: the hourly poll catches up
