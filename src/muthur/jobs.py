"""Long jobs in a background thread at low CPU priority (ARCHITECTURE.md §3, guardrails).

One job runs at a time (the NAS has two cores). A job started while another runs waits in a queue and
starts by itself afterwards, instead of being refused.
"""
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
    step: str | None = None  # the part of a long job running now, as a sentence; done/total count that part
    queued: bool = False  # waiting for the job before it
    by_user: bool = True  # started by the reader, not by the schedule
    result: str | None = None  # what it did, as a sentence (for the Kodi notification)
    attention: bool = False  # the result needs the reader (something couldn't be done): told even when quick

    @property
    def running(self) -> bool:
        return self.finished is None and not self.queued

    def as_dict(self) -> dict:
        return {**asdict(self), "running": self.running}

    def begin(self, step: str, total: int) -> None:
        """A new part of the job, with its own count, so the bar never sits full while work goes on."""
        self.step, self.total, self.done = step, total, 0


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
    def __init__(self, on_finish=None):
        """on_finish(job): called after every job, in its thread (for the Kodi notification)."""
        self.lock = threading.Lock()
        self.current: Job | None = None
        self.queue: list[tuple[Job, object]] = []
        self.last: dict[str, Job] = {}
        self.on_finish = on_finish

    def start(self, name: str, fn, by_user: bool = True) -> Job:
        """fn(job) does the work and may update job.done/total/step/result. While another job runs, this one
        waits in line (the same job is never queued twice) and starts by itself afterwards."""
        with self.lock:
            if self.current and self.current.running:
                if self.current.name == name:
                    return self.current
                for waiting, _ in self.queue:
                    if waiting.name == name:
                        return waiting
                job = Job(name, queued=True, by_user=by_user)
                self.queue.append((job, fn))
                return job
            job = self.current = Job(name, by_user=by_user)
        self._run(job, fn)
        return job

    def waiting(self) -> list[Job]:
        with self.lock:
            return [j for j, _ in self.queue]

    def _run(self, job: Job, fn) -> None:
        def run():
            _lower_priority()
            try:
                fn(job)
            except Exception as e:  # shown in the UI with a way out, not only in a log
                job.error = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                job.finished = time.time()
                self.last[job.name] = job
                if self.on_finish:
                    try:
                        self.on_finish(job)
                    except Exception:  # a notification must never break the queue
                        traceback.print_exc()
                self._next()

        threading.Thread(target=run, name=f"job-{job.name}", daemon=True).start()

    def _next(self) -> None:
        with self.lock:
            if not self.queue:
                return
            job, fn = self.queue.pop(0)
            job.queued, job.started = False, time.time()
            self.current = job
        self._run(job, fn)

    @contextmanager
    def exclusive(self, name: str):
        """Short work done in the request itself (an edit, a choice) under the same one-at-a-time rule,
        so a job can't start halfway and write the same files. Raises Busy when a job is running or waiting."""
        with self.lock:
            if (self.current and self.current.running) or self.queue:
                raise Busy(name)
            job = self.current = Job(name)
        try:
            yield job
        finally:
            job.finished = time.time()
            self.last[name] = job
            self._next()
