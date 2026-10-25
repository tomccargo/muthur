"""Review: choosing a match, mapping episodes a library numbers differently from TMDB, links."""
import os
import time
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from muthur.web import Config, create_app

# The Office (US) season 4 as TMDB has it: hour-long episodes are one entry, 14 in all.
# Libraries and releases often split them, 19 in all ('Goodbye Toby' is S04E18 and S04E19 there).
TMDB_S4 = ["Fun Run", "Dunder Mifflin Infinity", "Launch Party", "Money", "Local Ad", "Branch Wars", "Survivor Man",
           "The Deposition", "Dinner Party", "Chair Model", "Night Out", "Did I Stutter?", "Job Fair", "Goodbye Toby"]


class FakeTmdb:
    def __init__(self, token=None, cache_path=None):
        pass

    def search_tv(self, query, year=None):
        if "office" not in query.lower():
            return []
        return [{"id": 2316, "name": "The Office", "original_name": "The Office", "first_air_date": "2005-03-24",
                 "overview": "A mockumentary.", "poster_path": "/office.jpg", "popularity": 90, "origin_country": ["US"],
                 "original_language": "en"},
                {"id": 2996, "name": "The Office", "original_name": "The Office", "first_air_date": "2001-07-09",
                 "overview": "The British original.", "poster_path": "/uk.jpg", "popularity": 40, "origin_country": ["GB"],
                 "original_language": "en"}]

    def tv(self, i):
        if i not in (2316, 2996):
            return {}
        first = "2005-03-24" if i == 2316 else "2001-07-09"
        return {"id": i, "name": "The Office", "original_name": "The Office", "first_air_date": first, "original_language": "en",
                "overview": "A mockumentary.", "poster_path": "/office.jpg",
                "seasons": [{"season_number": 4, "episode_count": 14, "name": "Season 4"}], "external_ids": {}}

    def tv_season(self, i, n):
        return {"poster_path": "/s4.jpg", "episodes": [
            {"id": 6000 + k, "episode_number": k, "name": t, "air_date": "2008-01-01", "overview": f"Plot of {t}.",
             "runtime": 42 if t == "Goodbye Toby" else 22, "still_path": f"/e{k}.jpg"}
            for k, t in enumerate(TMDB_S4, 1)]} if n == 4 else {"episodes": []}

    def search_movie(self, query, year=None):
        return [{"id": 9, "title": "Solaris", "original_title": "Солярис", "release_date": "1972-03-20", "popularity": 10,
                 "original_language": "ru", "poster_path": "/sol72.jpg", "overview": "Tarkovsky."},
                {"id": 10, "title": "Solaris", "original_title": "Solaris", "release_date": "2002-11-27", "popularity": 30,
                 "original_language": "en", "poster_path": "/sol02.jpg", "overview": "Soderbergh."}] if "solaris" in query.lower() else []

    def movie(self, i):
        return {9: {"id": 9, "title": "Solaris", "original_title": "Солярис", "release_date": "1972-03-20", "runtime": 166,
                    "original_language": "ru", "poster_path": "/sol72.jpg"},
                10: {"id": 10, "title": "Solaris", "original_title": "Solaris", "release_date": "2002-11-27", "runtime": 99,
                     "original_language": "en", "poster_path": "/sol02.jpg"}}.get(i, {})

    def find(self, external_id, source):
        return {"tt0386676": {"tv_results": [self.tv(2316)]}, "tt0069293": {"movie_results": [self.movie(9)]}}.get(external_id, {})

    def tv_full(self, i):
        return {**self.tv(i), "images": {"logos": []}}

    def movie_full(self, i):
        return {**self.movie(i), "credits": {"cast": [], "crew": []}, "images": {"logos": []}}

    def image(self, path, size):
        return b"img" if path else None


def _old(path):
    t = time.time() - 3600
    os.utime(path, (t, t))


@pytest.fixture
def env(tmp_path, monkeypatch):
    dl, tv, film = tmp_path / "complete", tmp_path / "TV", tmp_path / "Film"
    season = tv / "The Office (US)" / "Season 04"
    season.mkdir(parents=True)
    film.mkdir()
    (season / "The Office S04E14 - The Chair Model - (2008) - SD.avi").write_bytes(b"old")
    files = {
        "toby": dl / "The Office US S04E19 Goodbye Toby Part 2 720p WEB-DL" / "The Office US S04E19 Goodbye Toby Part 2 720p WEB-DL.mkv",
        "branch": dl / "The.Office.US.S04E10.Branch.Wars.720p.WEB.mkv",
        "solaris": dl / "Solaris.720p.BluRay.x264.mkv",
    }
    for f in files.values():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"v" * 100)
        _old(f)
    for k, v in {"MUTHUR_CONFIG": tmp_path / "config", "MUTHUR_DOWNLOADS": dl, "MUTHUR_TV": tv, "MUTHUR_FILM": film,
                 "MUTHUR_QUARANTINE": tmp_path / "_q", "TMDB_READ_TOKEN": "x"}.items():
        monkeypatch.setenv(k, str(v))
    app = create_app(Config(dotenv=False), tmdb_factory=FakeTmdb)
    app.state.store.remember("tv", "The Office", 2316, 2005, "The Office", "The Office (US)", "library")
    client = TestClient(app)
    assert client.post("/api/inbox/scan").status_code == 202
    for _ in range(100):
        if not client.get("/api/status").json()["job"]["running"]:
            break
        time.sleep(0.05)
    return client, tmp_path, app


def _item(client, prefix):
    return next(i for i in client.get("/api/inbox").json()["items"] if i["id"].startswith(prefix))


TOBY = "The Office US S04E19 Goodbye Toby Part 2 720p WEB-DL"


def test_missing_episode_is_reviewed_with_a_suggestion(env):
    client, _, _ = env
    item = _item(client, TOBY)
    assert item["status"] == "review" and item["known"]
    f = item["files"][0]
    assert f["problem"] == "missing"
    assert f["suggestion"] == {"season": 4, "episode": 14, "title": "Goodbye Toby", "part": 2}
    assert f["parsed"]["episodeTitle"] == "Goodbye Toby"


def test_title_of_another_episode_is_not_filed_silently(env):
    client, _, _ = env
    item = _item(client, "The.Office.US.S04E10")
    # S04E10 exists on TMDB, but as 'Chair Model'; the file says 'Branch Wars', which is TMDB's E06.
    assert item["status"] == "review"
    assert item["files"][0]["problem"] == "other-episode"
    assert item["files"][0]["suggestion"]["episode"] == 6


def _toby_choice(client, number="file"):
    source = _item(client, TOBY)["files"][0]["source"]
    return {"kind": "tv", "tmdbId": 2316, "episodes": {source: {"season": 4, "episode": 14, "part": 2, "number": number}}}


def test_choosing_keeps_the_library_number_and_tmdb_data(env):
    client, tmp, _ = env
    r = client.post("/api/review/choose", json={"id": TOBY, "choice": _toby_choice(client)})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["status"] == "ready" and item["chosen"]
    f = item["files"][0]
    assert f["target"] == "The Office (US)/Season 04/The Office (US) - S04E19 - Goodbye Toby (2).mkv"
    assert (f["season"], f["episodes"], f["tmdb_season"], f["tmdb_episode"]) == (4, [19], 4, 14)
    assert _item(client, TOBY)["status"] == "ready"  # the inbox snapshot follows the choice

    client.post("/api/apply", json={"ids": [TOBY]})
    for _ in range(100):
        if not client.get("/api/status").json()["job"]["running"]:
            break
        time.sleep(0.05)
    nfo = tmp / "TV" / "The Office (US)" / "Season 04" / "The Office (US) - S04E19 - Goodbye Toby (2).nfo"
    root = ET.parse(nfo).getroot()
    assert root.findtext("episode") == "19" and root.findtext("season") == "4"
    assert root.findtext("title") == "Goodbye Toby (2)"
    assert root.findtext("plot") == "Plot of Goodbye Toby."
    assert root.findtext("uniqueid") == "6014"


def test_tmdb_number_that_is_taken_is_flagged(env):
    client, _, _ = env
    r = client.post("/api/review/preview", json={"id": TOBY, "choice": _toby_choice(client, number="tmdb")})
    f = r.json()["files"][0]
    assert f["target"].endswith("S04E14 - Goodbye Toby (2).mkv")
    # Another name than the existing 'The Office S04E14 - The Chair Model…', but the same number:
    # Kodi would list two S04E14s.
    assert f["problem"] == "exists"
    assert _item(client, TOBY)["status"] == "review"  # a preview changes nothing


def test_forget_puts_the_item_back(env):
    client, _, app = env
    client.post("/api/review/choose", json={"id": TOBY, "choice": _toby_choice(client)})
    assert app.state.store.choice(TOBY)
    item = client.post("/api/review/forget", json={"id": TOBY}).json()
    assert item["status"] == "review" and not item["chosen"]
    assert app.state.store.choice(TOBY) is None


def test_choosing_a_film_and_remembering_a_show(env):
    client, _, app = env
    film = _item(client, "Solaris")
    assert film["status"] == "review" and {c["tmdbId"] for c in film["candidates"]} == {9, 10}
    assert film["candidates"][0]["poster"]
    item = client.post("/api/review/choose", json={"id": film["id"], "choice": {"kind": "movie", "tmdbId": 9}}).json()
    assert item["status"] == "ready" and item["year"] == 1972
    assert item["files"][0]["target"].endswith("(1972).mkv")

    app.state.store.forget_library_except("tv", set())  # muthur no longer knows the show by name
    client.post("/api/review/choose", json={"id": TOBY, "choice": _toby_choice(client), "remember": True})
    assert [r["tmdb_id"] for r in app.state.store.lookup("tv", "The Office")] == [2316]


def test_choices_for_gone_downloads_are_dropped(env):
    client, tmp, app = env
    client.post("/api/review/choose", json={"id": "Solaris.720p.BluRay.x264.mkv", "choice": {"kind": "movie", "tmdbId": 10}})
    (tmp / "complete" / "Solaris.720p.BluRay.x264.mkv").unlink()
    client.post("/api/inbox/scan")
    for _ in range(100):
        if not client.get("/api/status").json()["job"]["running"]:
            break
        time.sleep(0.05)
    assert app.state.store.choice("Solaris.720p.BluRay.x264.mkv") is None


@pytest.mark.parametrize("link,kind,tmdb_id", [
    ("https://www.themoviedb.org/tv/2316-the-office", "tv", 2316),
    ("https://www.imdb.com/title/tt0386676/", "tv", 2316),
    ("tt0069293", "movie", 9),
])
def test_links_become_cards(env, link, kind, tmdb_id):
    client, _, _ = env
    card = client.post("/api/tmdb/resolve", json={"link": link}).json()
    assert (card["kind"], card["tmdbId"]) == (kind, tmdb_id)


def test_bad_link_and_bad_choice_are_refused(env):
    client, _, _ = env
    assert client.post("/api/tmdb/resolve", json={"link": "https://example.com"}).status_code == 422
    assert client.post("/api/review/choose", json={"id": TOBY, "choice": {"kind": "tv"}}).status_code == 422
    assert client.post("/api/review/choose", json={"id": "nope", "choice": {"kind": "movie", "tmdbId": 9}}).status_code == 404


def test_season_list_for_the_episode_question(env):
    client, _, _ = env
    data = client.get("/api/tmdb/tv/2316/season/4").json()
    assert data["seasons"] == [{"season": 4, "name": "Season 4", "episodes": 14}]
    assert data["episodes"][13]["title"] == "Goodbye Toby"
