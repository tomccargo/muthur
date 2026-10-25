"""API tests against a fake TMDB and a temporary downloads folder."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from muthur.web import Config, create_app


class FakeTmdb:
    def __init__(self, token, cache_path):
        pass

    def search_tv(self, query, year=None):
        return [{"id": 7, "name": "Some Show", "original_name": "Some Show", "first_air_date": "2021-01-01",
                 "popularity": 50, "origin_country": ["US"], "original_language": "en"}] if "some show" in query.lower() else []

    def tv(self, i):
        return {"id": 7, "name": "Some Show", "original_name": "Some Show", "first_air_date": "2021-01-01",
                "original_language": "en", "seasons": [{"season_number": 1, "episode_count": 8}],
                "external_ids": {"imdb_id": "tt0000007", "tvdb_id": 70}}

    def tv_season(self, i, n):
        return {"episodes": [{"episode_number": 2, "name": "The Second One"}]}

    def search_movie(self, query, year=None):
        return [{"id": 9, "title": "Some Film", "original_title": "Een Film", "original_language": "nl",
                 "release_date": "1999-05-01", "popularity": 10}] if "some film" in query.lower() else []

    def movie(self, i):
        return {"id": 9, "runtime": 100, "imdb_id": "tt0000009"}

    def tv_full(self, i):
        return {**self.tv(i), "overview": "Plot.", "poster_path": "/p.jpg"}

    def movie_full(self, i):
        return {"id": 9, "title": "Some Film", "original_title": "Een Film", "release_date": "1999-05-01", "runtime": 100}

    def image(self, path, size):
        return b"img" if path else None


def _old(path):
    t = time.time() - 3600
    os.utime(path, (t, t))


@pytest.fixture
def client(tmp_path):
    dl = tmp_path / "complete"
    (dl / "Some.Show.S01E02.1080p.WEB.h264-GRP").mkdir(parents=True)
    ep = dl / "Some.Show.S01E02.1080p.WEB.h264-GRP" / "some.show.s01e02.1080p.web.h264-grp.mkv"
    ep.write_bytes(b"x" * 10)
    note = dl / "Some.Show.S01E02.1080p.WEB.h264-GRP" / "Downloaded from site.txt"
    note.write_text("hi")
    film = dl / "Some.Film.1999.1080p.BluRay.x264-GRP.mkv"
    film.write_bytes(b"y" * 10)
    game = dl / "A Game [NSP]"
    game.mkdir()
    (game / "game.nsp").write_bytes(b"z")
    fresh = dl / "Some.Show.S01E03.mkv"
    fresh.write_bytes(b"new")
    category = dl / "tv-sonarr"
    (category / "Some.Show.S01E04.720p.HDTV").mkdir(parents=True)
    (category / "Some.Show.S01E05.720p.HDTV").mkdir()
    cat_eps = [category / f"Some.Show.S01E0{n}.720p.HDTV" / f"some.show.s01e0{n}.mkv" for n in (4, 5)]
    cat_eps.append(category / "Some.Show.S01E06.1080p.WEB.h264-GRP.mkv")  # a loose file in the category
    cat_eps.append(category / "Some.Show.S01E06.1080p.WEB.h264-GRP.en.srt")  # its subtitle: not an item of its own
    cat_eps.append(category / "Some Show S01E07 720p HDTV x264-GRP.exe")  # a program dressed up as an episode
    for p in cat_eps:
        p.write_bytes(b"c")
    pack = dl / "Some.Show.S02.COMPLETE"
    (pack / "Season 2").mkdir(parents=True)
    pack_eps = [pack / "Season 2" / f"some.show.s02e0{n}.mkv" for n in (1, 2)]
    for p in pack_eps:
        p.write_bytes(b"p")
    (pack / "Sample").mkdir()
    for p in (ep, note, film, game / "game.nsp", *cat_eps, *pack_eps):
        _old(p)

    os.environ["MUTHUR_CONFIG"] = str(tmp_path / "config")
    os.environ["MUTHUR_DOWNLOADS"] = str(dl)
    os.environ["MUTHUR_TV"] = str(tmp_path / "TV")
    os.environ["MUTHUR_FILM"] = str(tmp_path / "Film")
    os.environ["MUTHUR_WEB"] = str(tmp_path / "no-web")
    os.environ.pop("TMDB_READ_TOKEN", None)
    app = create_app(Config(dotenv=False), tmdb_factory=FakeTmdb)
    return TestClient(app)


def _scan(c):
    r = c.post("/api/inbox/scan")
    assert r.status_code == 202, r.text
    for _ in range(100):
        job = c.get("/api/jobs/current").json()
        if not job["running"]:
            assert job["error"] is None, job["error"]
            break
        time.sleep(0.05)
    return {i["id"]: i for i in c.get("/api/inbox").json()["items"]}


def test_scan_needs_a_tmdb_token(client):
    r = client.post("/api/inbox/scan")
    assert r.status_code == 409
    assert "TMDB" in r.json()["detail"]


def test_inbox_plans_without_moving(client, tmp_path):
    client.put("/api/settings", json={"tmdb": {"token": "fake"}})
    items = _scan(client)

    show = items["Some.Show.S01E02.1080p.WEB.h264-GRP"]
    assert show["status"] == "ready" and show["kind"] == "tv"
    assert show["files"][0]["target"] == "Some Show (2021)/Season 01/Some Show (2021) - S01E02 - The Second One.mkv"
    assert "tvshow.nfo" in show["files"][0]["writes"]

    film = items["Some.Film.1999.1080p.BluRay.x264-GRP.mkv"]
    assert film["status"] == "ready"
    assert film["files"][0]["target"] == "Een Film (1999)/Een Film (1999).mkv"  # Dutch keeps its original title

    # A category folder is opened up; a season pack with its own subfolders is not.
    assert items["tv-sonarr/Some.Show.S01E04.720p.HDTV"]["status"] == "ready"
    assert items["tv-sonarr/Some.Show.S01E05.720p.HDTV"]["status"] == "ready"
    assert items["tv-sonarr/Some.Show.S01E06.1080p.WEB.h264-GRP.mkv"]["status"] == "ready"
    assert "tv-sonarr/Some.Show.S01E06.1080p.WEB.h264-GRP.en.srt" not in items
    assert items["tv-sonarr/Some Show S01E07 720p HDTV x264-GRP.exe"]["status"] == "suspicious"
    assert "tv-sonarr" not in items
    assert len(items["Some.Show.S02.COMPLETE"]["files"]) == 2

    assert items["A Game [NSP]"]["status"] == "ignored"
    assert items["Some.Show.S01E03.mkv"]["status"] == "waiting"

    # Nothing was moved or created.
    assert (tmp_path / "complete" / "Some.Show.S01E02.1080p.WEB.h264-GRP" / "some.show.s01e02.1080p.web.h264-grp.mkv").exists()
    assert not (tmp_path / "TV").exists() and not (tmp_path / "Film").exists()


def test_status_and_settings(client):
    s = client.get("/api/status").json()
    assert s["applying"] is True and s["tmdb"]["configured"] is False and s["kodi"] is None
    r = client.put("/api/settings", json={"kodi": {"host": "shield", "port": "8080", "user": "kodi", "password": "pw"}})
    body = r.json()
    assert body["kodi"] == {"host": "shield", "port": 8080, "user": "kodi", "passwordSet": True}
    assert "password" not in str(body).replace("passwordSet", "")
    assert client.put("/api/settings", json={"kodi": {"port": "abc"}}).status_code == 422


def test_apply_then_undo_through_the_api(client, tmp_path):
    client.put("/api/settings", json={"tmdb": {"token": "fake"}})
    (tmp_path / "Film").mkdir()  # the library folder exists on a real NAS
    _scan(client)
    r = client.post("/api/apply", json={"ids": ["Some.Film.1999.1080p.BluRay.x264-GRP.mkv"]})
    assert r.status_code == 202, r.text
    for _ in range(100):
        if not client.get("/api/jobs/current").json()["running"]:
            break
        time.sleep(0.05)
    film = tmp_path / "Film" / "Een Film (1999)" / "Een Film (1999).mkv"
    assert film.exists() and (film.parent / "Een Film (1999).nfo").exists()
    assert not (tmp_path / "complete" / "Some.Film.1999.1080p.BluRay.x264-GRP.mkv").exists()

    runs = client.get("/api/history").json()["runs"]
    assert runs[0]["summary"]["applied"] == 1 and runs[0]["counts"]["move"] == 1

    assert client.post(f"/api/history/{runs[0]['id']}/undo").status_code == 202
    for _ in range(100):
        if not client.get("/api/jobs/current").json()["running"]:
            break
        time.sleep(0.05)
    assert (tmp_path / "complete" / "Some.Film.1999.1080p.BluRay.x264-GRP.mkv").exists()
    assert not (tmp_path / "Film" / "Een Film (1999)").exists()
    assert client.get("/api/history").json()["runs"][0]["undone"] is not None


def test_kodi_scan_needs_a_connection(client):
    r = client.post("/api/kodi/scan")
    assert r.status_code == 409 and "Settings" in r.json()["detail"]


def test_quarantine_lists_and_empties_only_on_confirmation(tmp_path, monkeypatch):
    q = tmp_path / "_q"
    (q / "2026-10-25" / "TV" / "Show").mkdir(parents=True)
    (q / "2026-10-25" / "TV" / "Show" / "old.mkv").write_bytes(b"x" * 10)
    (q / "not-a-day").mkdir()
    for k, v in {"MUTHUR_CONFIG": tmp_path / "config", "MUTHUR_DOWNLOADS": tmp_path / "dl", "MUTHUR_QUARANTINE": q}.items():
        monkeypatch.setenv(k, str(v))
    client = TestClient(create_app(Config(dotenv=False)))
    assert client.get("/api/quarantine").json() == {"days": [{"day": "2026-10-25", "files": 1, "size": 10}]}
    assert client.post("/api/quarantine/empty", json={"days": ["2026-10-25"]}).status_code == 422  # no confirmation
    assert client.post("/api/quarantine/empty", json={"days": ["../config"], "confirm": "delete"}).status_code == 422
    assert client.post("/api/quarantine/empty", json={"days": ["2026-10-25"], "confirm": "delete"}).json()["freed"] == 10
    assert not (q / "2026-10-25").exists() and (q / "not-a-day").exists()
