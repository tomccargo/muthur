"""One job at a time: a second one waits its turn; the reader is told on the TV when it matters."""
import threading
import time

import pytest

from muthur.jobs import Busy, Jobs


def _wait(predicate, seconds=5):
    end = time.time() + seconds
    while time.time() < end and not predicate():
        time.sleep(0.02)
    return predicate()


def test_a_second_job_waits_and_then_runs_by_itself():
    gate, ran, finished = threading.Event(), [], []
    jobs = Jobs(on_finish=lambda j: finished.append(j.name))
    first = jobs.start("health", lambda j: (gate.wait(5), ran.append("health")))
    second = jobs.start("inbox", lambda j: ran.append("inbox"))
    assert first.running and second.queued and not second.running
    assert jobs.start("inbox", lambda j: ran.append("twice")) is second  # never queued twice
    assert [j.name for j in jobs.waiting()] == ["inbox"]
    gate.set()
    assert _wait(lambda: ran == ["health", "inbox"])
    assert _wait(lambda: finished == ["health", "inbox"])
    assert not jobs.waiting()


def test_edits_wait_for_nothing_but_are_refused_while_a_job_runs_or_waits():
    gate = threading.Event()
    jobs = Jobs()
    jobs.start("scores", lambda j: gate.wait(5))
    with pytest.raises(Busy):
        with jobs.exclusive("edit"):
            pass
    gate.set()
    assert _wait(lambda: not jobs.current.running)
    with jobs.exclusive("edit"):
        pass


def test_the_tv_hears_about_what_needs_the_reader(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from muthur import web

    told = []
    monkeypatch.setattr(web.Kodi, "notify", lambda self, title, message, ms=8000: told.append(message) or True)
    for key, sub in (("MUTHUR_CONFIG", "config"), ("MUTHUR_DOWNLOADS", "complete"), ("MUTHUR_TV", "TV"),
                     ("MUTHUR_FILM", "Film"), ("MUTHUR_WEB", "no-web")):
        (tmp_path / sub).mkdir(exist_ok=True)
        monkeypatch.setenv(key, str(tmp_path / sub))
    app = web.create_app(web.Config(dotenv=False))
    TestClient(app).put("/api/settings", json={"kodi": {"host": "shield"}})
    jobs = app.state.jobs

    def quick(j):
        j.result = "Downloads checked: 1 ready, 0 need you."

    def needs_you(j):
        j.result, j.attention = "Put back, but 1 change(s) couldn't be: see History.", True

    def broken(j):
        raise OSError("disk gone")

    for name, fn in (("inbox", quick), ("undo", needs_you), ("apply", broken)):
        jobs.start(name, fn)
        assert _wait(lambda: not jobs.current.running)
    assert _wait(lambda: len(told) == 2)
    assert told == ["Put back, but 1 change(s) couldn't be: see History.", "Filing downloads stopped with a problem. Details in muthur."]
