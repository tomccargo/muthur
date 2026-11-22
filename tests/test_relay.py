"""The relay: Download Station and muthur's update through DSM's own synowebapi, and muthur talking to it through files."""
import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from muthur import relay
from muthur.downloadstation import DownloadStationError, Relay
from muthur.inbox import Inbox
from muthur.store import Store
from muthur.web import Config, create_app

TASKS = [{"id": "dbid_1", "title": "Some.Show.S01E02.1080p.WEB", "status": 8, "size": 100,
          "additional": {"detail": {"destination": "Iedereen/torrent-output"}, "transfer": {"size_downloaded": 100}}},
         {"id": "dbid_2", "title": "Some.Film.1999.mkv", "status": 5, "size": 0, "additional": {}},
         {"id": "dbid_3", "title": "Still.Coming.S01E01", "status": 2, "size": 200,
          "additional": {"transfer": {"size_downloaded": 50}}}]


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class FakeHost:
    """Stands in for nsenter: records each command and answers synowebapi and docker like DSM does."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.deleted: list[str] = []

    def __call__(self, args, capture_output=True, text=True, timeout=None):
        assert args[: len(relay.HOST)] == relay.HOST  # always on the host, never through a shell
        cmd = args[len(relay.HOST):]
        self.calls.append(cmd)
        if cmd[0] == relay.SYNOWEBAPI:
            params = dict(a.split("=", 1) for a in cmd[2:])
            if params["api"] == "SYNO.DownloadStation2.Task" and params["method"] == "list":
                return Done("synowebapi log line\n" + json.dumps({"success": True, "data": {"task": TASKS, "total": 3}}))
            if params["method"] == "delete":
                ids = json.loads(params["id"])
                self.deleted += ids
                return Done(json.dumps({"success": True, "data": {"failed_task": [{"id": i, "error": 0} for i in ids]}}))
            return Done(json.dumps({"success": False, "error": {"code": 102}}))
        return Done("")


def test_status_numbers_get_names_and_progress():
    host = FakeHost()
    tasks = relay.ds_list("torrent", host)["tasks"]
    assert [(t["id"], t["status"], t["progress"]) for t in tasks] == [("dbid_1", "seeding", 100), ("dbid_2", "finished", None),
                                                                      ("dbid_3", "downloading", 25)]
    assert tasks[0]["destination"] == "Iedereen/torrent-output"
    call = host.calls[0]
    assert "runner=torrent" in call and 'additional=["detail", "transfer"]' in call and "limit=-1" in call


def test_delete_takes_only_task_ids():
    host = FakeHost()
    assert relay.ds_delete("torrent", ["dbid_1", "dbid_2"], host) == {"ok": True, "failed": []}
    assert host.deleted == ["dbid_1", "dbid_2"]
    assert "force_complete=false" in host.calls[0]
    for bad in (["dbid_1; rm -rf /"], "dbid_1", [], ["../x"], [1]):
        assert relay.ds_delete("torrent", bad, host)["ok"] is False
    assert len(host.calls) == 1


def test_the_spool_answers_each_request_and_refuses_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("MUTHUR_IMAGE", "")
    (tmp_path / "a.req.json").write_text(json.dumps({"op": "list"}))
    (tmp_path / "b.req.json").write_text(json.dumps({"op": "exec", "cmd": "sh"}))
    (tmp_path / "c.req.json").write_text("not json")
    (tmp_path / "d.req.json").write_text(json.dumps({"op": "pull"}))
    assert relay.once(str(tmp_path), "torrent", FakeHost()) == 4
    answers = {n[0]: json.loads((tmp_path / n).read_text()) for n in os.listdir(tmp_path) if n.endswith(".res.json")}
    assert answers["a"]["ok"] and len(answers["a"]["tasks"]) == 3
    assert answers["b"] == {"ok": False, "error": "The relay doesn't do that."}
    assert answers["c"]["ok"] is False
    assert "off" in answers["d"]["error"]
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".req.json")]


def test_without_a_dsm_user_it_says_so(tmp_path):
    (tmp_path / "a.req.json").write_text(json.dumps({"op": "list"}))
    relay.once(str(tmp_path), "", FakeHost())
    assert "DS_USER" in json.loads((tmp_path / "a.res.json").read_text())["error"]


def test_the_dsm_user_is_checked(monkeypatch):
    monkeypatch.setenv("DS_USER", "torrent")
    assert relay.runner() == "torrent"
    monkeypatch.setenv("DS_USER", "x; reboot")
    assert relay.runner() == ""


def test_an_update_pulls_then_rebuilds_from_muthurs_own_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("MUTHUR_IMAGE", "tomccargo/muthur:latest")

    class Docker(FakeHost):
        def __call__(self, args, capture_output=True, text=True, timeout=None):
            cmd = args[len(relay.HOST):]
            self.calls.append(cmd)
            if cmd[:2] == [relay.DOCKER, "pull"]:
                return Done("sha256:new")
            if cmd[:3] == [relay.DOCKER, "image", "inspect"]:
                return Done("sha256:new\n")
            if cmd[:2] == [relay.DOCKER, "inspect"] and cmd[-1] == "muthur" and "{{.Image}}" in cmd:
                return Done("sha256:old\n")
            if cmd[:2] == [relay.DOCKER, "inspect"] and cmd[-1] == "muthur":
                return Done(json.dumps({"com.docker.compose.project": "muthur",
                                        "com.docker.compose.project.config_files": "/volume1/docker/muthur/compose.yaml"}))
            if cmd[:2] == [relay.DOCKER, "inspect"] and cmd[-1] == "muthur-relay":
                return Done(json.dumps([{"Source": "/volume1/docker/muthur/config/relay", "Destination": str(tmp_path)}]))
            return Done("abc123")

    host = Docker()
    relay.pull(str(tmp_path), host)
    assert json.loads((tmp_path / "update.json").read_text())["state"] == "pulled"
    assert relay.rebuild(str(tmp_path), host) == {"ok": True}
    run = host.calls[-1]
    assert run[:4] == [relay.DOCKER, "run", "-d", "--rm"] and "muthur-update" in run
    assert "/volume1/docker/muthur/config/relay:/spool" in run and "MUTHUR_COMPOSE=/volume1/docker/muthur/compose.yaml" in run
    assert run[-4:] == ["python", "-m", "muthur.relay", "--rebuild"]
    assert json.loads((tmp_path / "update.json").read_text())["state"] == "rebuilding"


BUILD_FAILED = ("Content-Type: text/html\n\n Container muthur  Running\n Container muthur-relay  Starting\n"
                "Error response from daemon: Bind mount failed: '/volume1/docker/muthur/config/relay' does not exist\nExit Code: 1\n\n"
                "[Line 295] Exec WebAPI:  api=SYNO.Docker.Project, version=1, method=build_stream\n"
                '{\n   "error" : {\n      "code" : 2202\n   },\n   "httpd_restart" : false,\n   "success" : false\n}\n')  # Nostromo, 2026-11-22


@pytest.mark.parametrize("answer, state", [(BUILD_FAILED, "failed"), ("Exit Code: 0\n\n{\n   \"httpd_restart\" : false,\n   \"success\" : true\n}\n", "done")])
def test_the_rebuild_reports_what_container_manager_said(tmp_path, monkeypatch, answer, state):
    monkeypatch.setenv("MUTHUR_PROJECT", "muthur")
    monkeypatch.setenv("MUTHUR_COMPOSE", "/volume1/docker/muthur/compose.yaml")

    def host(args, capture_output=True, text=True, timeout=None):
        cmd = args[len(relay.HOST):]
        if cmd[0] == "/bin/cat":
            return Done("services: {}\n")
        if "method=list" in cmd:
            return Done(json.dumps({"success": True, "data": {"abc": {"id": "abc", "name": "muthur"}}}))
        if "method=update" in cmd:
            return Done(json.dumps({"success": True}))
        return Done(answer)
    relay.rebuild_project(str(tmp_path), host)
    result = json.loads((tmp_path / "update.json").read_text())
    assert result["state"] == state
    if state == "failed":
        assert "error 2202" in result["problem"] and "Bind mount failed" in result["problem"]


def test_the_same_image_is_current(tmp_path, monkeypatch):
    monkeypatch.setenv("MUTHUR_IMAGE", "tomccargo/muthur:latest")

    def same(args, capture_output=True, text=True, timeout=None):
        return Done("sha256:same\n")
    relay.pull(str(tmp_path), same)
    assert json.loads((tmp_path / "update.json").read_text())["state"] == "current"


def test_updates_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MUTHUR_IMAGE", "tomccargo/muthur:latest")
    monkeypatch.setenv("MUTHUR_UPDATES", "off")
    assert relay.image() == ""


# -- muthur's side ---------------------------------------------------------------------
@pytest.fixture
def running_relay(tmp_path):
    """A relay serving tmp_path/relay with the fake host, as the container would."""
    spool = tmp_path / "relay"
    spool.mkdir()
    host, stop = FakeHost(), threading.Event()
    # Written once: a test is over long before it goes stale (and Windows can't replace a file another thread reads).
    relay.write_json(str(spool / "relay.alive"), {"at": int(time.time()), "user": "torrent", "updates": False})

    def serve():
        while not stop.is_set():
            relay.once(str(spool), "torrent", host)
            time.sleep(0.05)
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield spool, host
    stop.set()
    t.join()


def test_muthur_removes_finished_tasks_through_the_relay(running_relay):
    spool, host = running_relay
    r = Relay(str(spool))
    assert r.state()["user"] == "torrent"
    result = r.remove_finished({"Some.Show.S01E02.1080p.WEB", "Some.Film.1999.mkv", "Still.Coming.S01E01"})
    assert result == {"removed": ["Some.Show.S01E02.1080p.WEB", "Some.Film.1999.mkv"], "notFinished": ["Still.Coming.S01E01"]}
    assert host.deleted == ["dbid_1", "dbid_2"]
    assert not [n for n in os.listdir(spool) if n.endswith((".req.json", ".res.json"))]


def test_a_relay_that_isnt_running_is_not_used(tmp_path):
    spool = tmp_path / "relay"
    spool.mkdir()
    relay.write_json(str(spool / "relay.alive"), {"at": int(time.time()) - 600, "user": "torrent"})
    assert Relay(str(spool)).state() is None
    with pytest.raises(DownloadStationError):
        Relay(str(spool), timeout=0.3).tasks()
    assert os.listdir(spool) == ["relay.alive"]  # the unanswered request was taken back


def test_the_inbox_trusts_download_station_over_the_clock(tmp_path):
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Some.Notes.txt").write_text("v")  # just written, yet Download Station says it is finished
    old = dl / "Still.Coming.S01E01"
    old.mkdir()
    (old / "still.coming.s01e01.mkv").write_bytes(b"v")
    t = time.time() - 3600
    os.utime(old / "still.coming.s01e01.mkv", (t, t))  # quiet for an hour, yet Download Station is still downloading it
    store = Store(str(tmp_path / "m.db"))
    tasks = {"Some.Notes.txt": {"status": "finished"}, "Still.Coming.S01E01": {"status": "downloading", "progress": 25}}
    inbox = Inbox(None, store, str(dl), tasks=tasks)
    coming = inbox.examine("Still.Coming.S01E01")
    assert coming.status == "waiting" and coming.reason.startswith("Download Station: downloading, 25%")
    assert inbox.examine("Some.Notes.txt").status == "ignored"  # looked at right away: not video
    assert Inbox(None, store, str(dl)).examine("Some.Notes.txt").status == "waiting"  # no Download Station: the clock decides


def test_settings_show_the_relay_and_the_test_uses_it(tmp_path, running_relay, monkeypatch):
    monkeypatch.setenv("MUTHUR_CONFIG", str(tmp_path))
    monkeypatch.setenv("MUTHUR_DOWNLOADS", str(tmp_path / "dl"))
    monkeypatch.setenv("MUTHUR_WEB", str(tmp_path / "no-web"))
    c = TestClient(create_app(Config(dotenv=False)))
    ds = c.get("/api/settings").json()["downloadStation"]
    assert ds["relay"] == {"user": "torrent", "updates": False} and ds["lastCleanUp"] is None
    assert c.post("/api/downloadstation/test").json() == {"connected": True, "tasks": 3, "via": "relay"}
    u = c.get("/api/update").json()
    assert u["possible"] is False
    assert c.post("/api/update").status_code == 409
