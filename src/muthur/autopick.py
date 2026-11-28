"""Automatic pick-up: a finished download goes into the library without the reader starting it.

The watcher (web.py, auto_look) looks at the downloads folder once a minute. That look is cheap: the downloads' names,
sizes and times, and Download Station's task list when the relay runs. It starts a pick-up only when

- a download has settled since the last look: Download Station says it is finished or seeding, or, without a task,
  nothing in it changed for 10 minutes (the Inbox's own rule, inbox.SETTLE_SECONDS), and
- muthur is idle: no job runs or waits (the busy state /api/health reports), so it never cuts into the reader's work.

A pick-up does what the reader would: check the downloads, unpack the archives that hold a video (fakes go to quarantine),
and file what is Ready. A download that needs a choice stays in Review for the reader. Nothing is done twice: each
download is tried once in each state (its files, sizes and times; `tried`), and a filed download has left the folder.
What it did is kept in a short log for the Inbox (`log`).
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from .downloadstation import DONE as TASK_DONE
from .inbox import SETTLE_SECONDS

LOG = "auto.log"
TRIED = "auto.tried"
KEEP = 100  # log lines kept
EVERY = 60  # seconds between two looks


def state_of(base: str, entry: str) -> list:
    """[files, bytes, newest change] of a download: what changes while it is written, and after it is unpacked."""
    path = os.path.join(base, *entry.split("/"))
    files = size = 0
    newest = 0.0
    try:
        if os.path.isfile(path):
            st = os.stat(path)
            return [1, st.st_size, st.st_mtime]
        for dp, _, names in os.walk(path):
            for n in names:
                try:
                    st = os.stat(os.path.join(dp, n))
                except OSError:
                    continue
                files, size, newest = files + 1, size + st.st_size, max(newest, st.st_mtime)
    except OSError:
        pass
    return [files, size, newest]


def settled(state: list, task: dict | None, now: float) -> bool:
    """Download Station knows best; without a task, the 10-minute rule. An empty download never is."""
    if task:
        return task.get("status") in TASK_DONE
    return state[0] > 0 and now - state[2] >= SETTLE_SECONDS


def look_key(base: str, entries: list[str], tasks: dict[str, dict] | None, now: float) -> str:
    """A fingerprint of the settled downloads: when it changes, there is something new to pick up."""
    rows = []
    for e in entries:
        state = state_of(base, e)
        if settled(state, (tasks or {}).get(e.rsplit("/", 1)[-1]), now):
            rows.append([e, *state])
    return hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()[:20]


class Memory:
    """What the pick-up already tried, and its log, in muthur's store."""

    def __init__(self, store):
        self.store = store
        self.tried: dict[str, list] = dict(store.get(TRIED) or {})

    def new(self, entry: str, state: list) -> bool:
        return self.tried.get(entry) != state

    def mark(self, entry: str, state: list) -> None:
        self.tried[entry] = state

    def save(self, present: set[str]) -> None:
        """Forget downloads that left the folder: a new one by the same name is new."""
        self.store.put(TRIED, {k: v for k, v in self.tried.items() if k in present})


def log(store, rows: list[dict]) -> None:
    """Newest first; each row: {id, what, title?, year?, why?, run?}. what: filed | stopped | review | planned |
    unpacked | quarantined | left."""
    if not rows:
        return
    now = time.time()
    store.put(LOG, ([{"at": now, **r} for r in rows] + list(store.get(LOG) or []))[:KEEP])


def summary(rows: list[dict]) -> str | None:
    """One sentence for the job and the TV: what was filed and what needs the reader."""
    filed = [r for r in rows if r["what"] == "filed"]
    review = sum(r["what"] == "review" for r in rows)
    stopped = sum(r["what"] == "stopped" for r in rows)
    if not (filed or review or stopped):
        return None
    names = ", ".join(r.get("title") or r["id"].rsplit("/", 1)[-1] for r in filed[:3]) + (" and more" if len(filed) > 3 else "")
    parts = [f"Filed {names}" if filed else ""]
    if review:
        parts.append(f"{review} need{'s' if review == 1 else ''} you in Review")
    if stopped:
        parts.append(f"{stopped} couldn't be filed")
    return "; ".join(p for p in parts if p) + "."
