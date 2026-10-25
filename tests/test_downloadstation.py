"""Download Station: log in, list, and remove only finished tasks of moved downloads."""
import pytest

from muthur import downloadstation
from muthur.downloadstation import DownloadStation, DownloadStationError


class Answer:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def calls(monkeypatch):
    seen = []
    tasks = [{"id": "dbid_1", "title": "Some.Show.S01E02.1080p.WEB", "status": "seeding"},
             {"id": "dbid_2", "title": "Some.Film.1999.mkv", "status": "finished"},
             {"id": "dbid_3", "title": "Still.Coming.S01E01", "status": "downloading"},
             {"id": "dbid_4", "title": "Something.Else", "status": "finished"}]

    def get(url, params, timeout, verify):
        seen.append((url.rsplit("/webapi/", 1)[1], params))
        if params["api"] == "SYNO.API.Auth":
            ok = params["passwd"] == "right"
            return Answer({"success": True, "data": {"sid": "abc"}} if ok else {"success": False, "error": {"code": 400}})
        if params["method"] == "list":
            return Answer({"success": True, "data": {"tasks": tasks}})
        return Answer({"success": True, "data": [{"error": 0, "id": i} for i in params["id"].split(",")]})

    monkeypatch.setattr(downloadstation.requests, "get", get)
    return seen


def test_only_finished_tasks_of_moved_downloads_are_removed(calls):
    ds = DownloadStation("http://nas:5000", "muthur", "right")
    result = ds.remove_finished({"Some.Show.S01E02.1080p.WEB", "Some.Film.1999.mkv", "Still.Coming.S01E01"})
    assert result == {"removed": ["Some.Show.S01E02.1080p.WEB", "Some.Film.1999.mkv"], "notFinished": ["Still.Coming.S01E01"]}
    delete = [p for path, p in calls if p.get("method") == "delete"]
    assert delete == [{"api": "SYNO.DownloadStation.Task", "version": 1, "method": "delete", "id": "dbid_1,dbid_2",
                       "force_complete": "false", "_sid": "abc"}]


def test_a_wrong_password_says_so(calls):
    assert DownloadStation("http://nas:5000", "muthur", "wrong").check() == {"connected": False, "problem": "The account or password is wrong."}
    with pytest.raises(DownloadStationError):
        DownloadStation("http://nas:5000", "muthur", "wrong").tasks()
