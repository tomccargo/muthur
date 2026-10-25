"""Every change muthur makes to the library, recorded before it happens, so any run can be undone.

Operations: mkdir (a folder muthur created), move (a rename on the same disk; never
copy-then-delete), write (a file muthur created; never an overwrite) and quarantine
(a move into the quarantine folder). Undo replays a run backwards and only touches a
file that is still exactly what muthur left there.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,           -- 'apply'
    started REAL NOT NULL,
    finished REAL,
    summary TEXT,                 -- JSON
    undone REAL
);
CREATE TABLE IF NOT EXISTS ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    item TEXT NOT NULL,           -- the inbox item this belongs to
    op TEXT NOT NULL,             -- mkdir | move | write | quarantine
    src TEXT,                     -- absolute path before
    dst TEXT NOT NULL,            -- absolute path after
    size INTEGER,
    digest TEXT,                  -- fingerprint of what is at dst, checked before undoing
    status TEXT NOT NULL,         -- done | undone | failed
    at REAL NOT NULL,
    error TEXT
);
"""


def fingerprint(path: str) -> str:
    """Size plus a hash of the first and last MB: quick on multi-GB videos, still exact enough."""
    size = os.path.getsize(path)
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
    return h.hexdigest()


class Journal:
    def __init__(self, store):
        self.store = store
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()

    def _exec(self, sql: str, args=()):
        with self.store.lock:
            cur = self.store.db.execute(sql, args)
            self.store.db.commit()
            return cur

    def start(self, kind: str) -> int:
        return self._exec("INSERT INTO runs (kind, started) VALUES (?, ?)", (kind, time.time())).lastrowid

    def finish(self, run_id: int, summary: dict) -> None:
        self._exec("UPDATE runs SET finished = ?, summary = ? WHERE id = ?", (time.time(), json.dumps(summary), run_id))

    def record(self, run_id: int, item: str, op: str, src: str | None, dst: str, size: int | None = None,
               digest: str | None = None, status: str = "done", error: str | None = None) -> int:
        return self._exec(
            "INSERT INTO ops (run_id, item, op, src, dst, size, digest, status, at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, item, op, src, dst, size, digest, status, time.time(), error)).lastrowid

    def mark(self, op_id: int, status: str, error: str | None = None) -> None:
        self._exec("UPDATE ops SET status = ?, error = ? WHERE id = ?", (status, error, op_id))

    def ops(self, run_id: int, item: str | None = None) -> list[dict]:
        q = "SELECT * FROM ops WHERE run_id = ?" + (" AND item = ?" if item else "") + " ORDER BY id"
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute(q, (run_id, item) if item else (run_id,)).fetchall()]

    def runs(self, limit: int = 50) -> list[dict]:
        with self.store.lock:
            rows = self.store.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d["summary"]) if d["summary"] else None
            out.append(d)
        return out

    def mark_run_undone(self, run_id: int) -> None:
        self._exec("UPDATE runs SET undone = ? WHERE id = ?", (time.time(), run_id))

    # -- undo ---------------------------------------------------------------------
    def undo(self, run_id: int, item: str | None = None) -> dict:
        """Put back what a run (or one item of it) did, newest change first. A file that changed
        since muthur touched it is left alone and reported, never overwritten or deleted."""
        result = {"undone": 0, "skipped": [], "item": item}
        for o in reversed(self.ops(run_id, item)):
            if o["status"] != "done":
                continue
            try:
                problem = self._undo_one(o)
            except OSError as e:
                problem = f"{e.strerror or e}"
            if problem:
                result["skipped"].append({"path": o["dst"], "why": problem})
                self.mark(o["id"], "done", problem)
            else:
                self.mark(o["id"], "undone")
                result["undone"] += 1
        if item is None and not result["skipped"]:
            self.mark_run_undone(run_id)
        return result

    @staticmethod
    def _undo_one(o: dict) -> str | None:
        op, src, dst = o["op"], o["src"], o["dst"]
        if op == "mkdir":
            if os.path.isdir(dst):
                if os.listdir(dst):
                    return "the folder isn't empty any more"
                os.rmdir(dst)
            return None
        if not os.path.lexists(dst):
            return "it isn't there any more"
        if o["digest"] and fingerprint(dst) != o["digest"]:
            return "it changed after muthur wrote it"
        if op == "write":
            os.remove(dst)
            return None
        # move / quarantine: back to where it came from, never over something new
        if os.path.lexists(src):
            return "something else now has its old name"
        os.makedirs(os.path.dirname(src), exist_ok=True)
        os.rename(dst, src)
        return None
