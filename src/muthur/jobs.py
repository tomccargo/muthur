"""Long jobs in a background thread at low CPU priority (ARCHITECTURE.md §3, guardrails)."""
from __future__ import annotations

import os
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field


@dataclass
class Job:
    name: str
    started: float = field(default_factory=time.time)
    finished: float | None = None
    done: int = 0
    total: int = 0
    error: str | None = None

    @property
    def running(self) -> bool:
        return self.finished is None

    def as_dict(self) -> dict:
        return {**asdict(self), "running": self.running}


def _lower_priority() -> None:
    """Nice this thread only (Linux keeps a nice value per thread); interactive requests stay at normal priority."""
    if hasattr(os, "setpriority"):
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except OSError:
            pass


class Busy(Exception):
    """Another job is running."""


class Jobs:
    """At most one long job at a time: the NAS has two cores."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current: Job | None = None
        self.last: dict[str, Job] = {}

    def start(self, name: str, fn) -> Job | None:
        """fn(job) does the work and may update job.done/total. Returns None when another job is running."""
        with self.lock:
            if self.current and self.current.running:
                return None
            job = self.current = Job(name)

        def run():
            _lower_priority()
            try:
                fn(job)
            except Exception as e:  # shown in the UI with a way out, not only in a log
                job.error = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                job.finished = time.time()
                self.last[name] = job

        threading.Thread(target=run, name=f"job-{name}", daemon=True).start()
        return job

    @contextmanager
    def exclusive(self, name: str):
        """Short work done in the request itself (an edit, a choice) under the same one-at-a-time rule,
        so a job can't start halfway and write the same files. Raises Busy when a job is running."""
        with self.lock:
            if self.current and self.current.running:
                raise Busy(name)
            job = self.current = Job(name)
        try:
            yield job
        finally:
            job.finished = time.time()
            self.last[name] = job
