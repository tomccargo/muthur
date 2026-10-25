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

    def get(url, params, timeout, verify=True):
        seen.append(("GET", url.rsplit("/webapi/", 1)[1], params))
        return answer(params)

    def answer(params):
        if params["api"] == "SYNO.API.Auth":
            ok = params["passwd"] == "right"
            return Answer({"success": True, "data": {"sid": "abc"}} if ok else {"success": False, "error": {"code": 400}})
        if params["method"] == "list":
            return Answer({"success": True, "data": {"tasks": tasks}})
        return Answer({"success": True, "data": [{"error": 0, "id": i} for i in params["id"].split(",")]})

    def post(url, data, timeout):
        seen.append(("POST", url.rsplit("/webapi/", 1)[1], dict(data)))
        return answer(data)

    monkeypatch.setattr(downloadstation.requests, "get", get)
    monkeypatch.setattr(downloadstation.requests, "post", post)
    return seen


def test_only_finished_tasks_of_moved_downloads_are_removed(calls):
    ds = DownloadStation("http://nas:5000", "muthur", "right")
    result = ds.remove_finished({"Some.Show.S01E02.1080p.WEB", "Some.Film.1999.mkv", "Still.Coming.S01E01"})
    assert result == {"removed": ["Some.Show.S01E02.1080p.WEB", "Some.Film.1999.mkv"], "notFinished": ["Still.Coming.S01E01"]}
    delete = [p for _, path, p in calls if p.get("method") == "delete"]
    assert delete == [{"api": "SYNO.DownloadStation.Task", "version": 1, "method": "delete", "id": "dbid_1,dbid_2",
                       "force_complete": "false", "_sid": "abc"}]


def test_a_wrong_password_says_so(calls):
    assert DownloadStation("http://nas:5000", "muthur", "wrong").check() == {"connected": False, "problem": "The account or password is wrong."}
    with pytest.raises(DownloadStationError):
        DownloadStation("http://nas:5000", "muthur", "wrong").tasks()


def test_the_password_goes_in_the_body_never_in_a_url(calls):
    DownloadStation("http://nas:5000", "dl", "right").check()
    logins = [c for c in calls if c[0] == "POST"]
    assert logins and logins[0][2]["passwd"] == "right"
    assert not any("passwd" in c[2] for c in calls if c[0] == "GET")  # every GET carries only the session
