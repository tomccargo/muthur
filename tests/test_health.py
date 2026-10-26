"""Health: which problems become safe fixes, which become questions, and applying the fixes."""
import gzip
import xml.etree.ElementTree as ET

import pytest

from muthur.health import Health
from muthur.imdb import Imdb
from muthur.index import Index
from muthur.journal import Journal
from muthur.store import Store

EPISODES = "tconst\tparentTconst\tseasonNumber\tepisodeNumber\n" + "".join(f"tt20{n}\ttt100\t1\t{n}\n" for n in range(1, 4))
RATINGS = "tconst\taverageRating\tnumVotes\ntt100\t8.0\t5000\ntt201\t7.1\t100\ntt202\t7.2\t200\ntt203\t7.3\t300\ntt900\t8.1\t90000\n"
SONARR_EP = ('<?xml version="1.0" encoding="utf-8"?>\n<episodedetails>\n  <title>Two</title>\n  <season>1</season>\n  <episode>2</episode>\n'
             '  <ratings>\n    <rating name="tvdb" max="10" default="true">\n      <value>7.0</value>\n      <votes>5</votes>\n    </rating>\n'
             '  </ratings>\n  <uniqueid type="tvdb" default="true">5</uniqueid>\n</episodedetails>\n')


class FakeTmdb:
    def tv(self, i):
        if i == 8:
            return {"id": 8, "name": "Other Show", "first_air_date": "2019-01-01", "seasons": [{"season_number": 1, "episode_count": 3}],
                    "external_ids": {"imdb_id": "tt800"}}
        return {"id": 7, "name": "Some Show", "seasons": [{"season_number": 1, "episode_count": 3}, {"season_number": 2, "episode_count": 2}],
                "external_ids": {"imdb_id": "tt100"}}

    def search_tv(self, query, year=None):
        return [{"id": 8, "name": "Other Show", "original_name": "Other Show", "first_air_date": "2019-01-01", "popularity": 5}]             if query.lower() == "other show" else []

    def search_movie(self, query, year=None):
        if query.lower() == "unknown film":
            return [{"id": 50, "title": "Unknown Film", "original_title": "Unknown Film", "release_date": "2005-01-01", "popularity": 3}]
        if query.lower() == "mystery":  # two films share the name and the file has no year: a question
            return [{"id": 60, "title": "Mystery", "original_title": "Mystery", "release_date": "1990-01-01", "popularity": 3},
                    {"id": 61, "title": "Mystery", "original_title": "Mystery", "release_date": "2012-01-01", "popularity": 3}]
        return []

    def movie(self, i):
        return {"id": i, "runtime": None}

    def movie_full(self, i):
        return {"id": i, "title": "Unknown Film", "original_title": "Unknown Film", "original_language": "en", "release_date": "2005-01-01",
                "poster_path": "/mp.jpg", "images": {"logos": []}}

    def tv_full(self, i):
        return {**self.tv(i), "first_air_date": "2021-01-01", "poster_path": "/p.jpg", "images": {"logos": []}}

    def tv_season(self, i, n):
        names = {1: ["One", "Two", "Three"], 2: ["Alpha", "Beta"]}[n]
        return {"episodes": [{"id": 100 * n + k, "episode_number": k, "name": t, "still_path": f"/s{n}{k}.jpg"} for k, t in enumerate(names, 1)]}

    def image(self, path, size):
        return b"img" if path else None


def write(p, data="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    show = tv / "Some Show"
    write(show / "tvshow.nfo", '<tvshow><title>Some Show</title><uniqueid type="tmdb">7</uniqueid></tvshow>')
    s1, s2 = show / "Season 01", show / "Season 02"
    write(s1 / "Some Show - S01E01 - One.mkv")  # no NFO: a fix
    write(s1 / "Some Show - S01E02 - Two.mkv")
    write(s1 / "Some Show - S01E02 - Two.nfo", SONARR_EP)  # no IMDb score: a fix
    write(s1 / "Some Show - S01E03 - Two.mkv")  # named after TMDB's S01E02: a question
    write(s2 / "Some Show - S02E01 - Alpha.mkv")
    write(s2 / "Some Show - S02E02 - Beta.mkv")  # in a season numbered differently, but its title confirms it: a fix
    write(s2 / "Some Show - S02E05 - Extra.mkv")  # season 2 goes beyond TMDB's 2: a question for this episode
    write(s1 / "Some.Show.S10E-1.mkv")  # damaged number: a question
    write(s1 / "Downloaded from site.txt")  # junk: a fix
    write(film / "Empty (2001)" / "poster.jpg")  # no video: a fix
    write(film / "Solaris (1972)" / "Solaris (1972).mkv")
    write(film / "Solaris (1972)" / "Solaris (1972).nfo", '<movie>\n  <title>Solaris</title>\n  <uniqueid type="imdb">tt900</uniqueid>\n</movie>\n')
    write(film / "Unknown Film" / "Unknown.Film.mkv")  # no NFO, but TMDB knows it for certain: a fix
    write(film / "Mystery" / "Mystery.mkv")  # no NFO, two films by that name: a question
    write(tv / "Other Show (2019)" / "Season 01" / "Other Show - S01E01 - One.mkv")  # no NFOs, TMDB knows the show: fixes
    store = Store(str(tmp_path / "muthur.db"))
    files = {"title.episode.tsv.gz": EPISODES, "title.ratings.tsv.gz": RATINGS}
    imdb = Imdb(store, base="", opener=lambda url: __import__("io").BytesIO(gzip.compress(files[url].encode())))
    imdb.refresh({"tt100"}, {"tt900"})
    index = Index(store, str(tv), str(film))
    health = Health(store, Journal(store), imdb, FakeTmdb(), index, str(tv), str(film), str(tmp_path / "_q"), str(tmp_path / "backups"))
    return tmp_path, health, health.check(index.build())


def test_problems_sorted_into_fixes_and_questions(env):
    _, _, plan = env
    paths = {k: sorted(x["path"].rsplit("/", 1)[-1] for x in v) for k, v in plan["fixes"].items()}
    assert paths["leftovers"] == ["Downloaded from site.txt"]
    assert paths["empty-films"] == ["Empty (2001)"]
    assert paths["episode-nfos"] == ["Other Show - S01E01 - One.nfo", "Some Show - S01E01 - One.nfo", "Some Show - S02E01 - Alpha.nfo",
                                     "Some Show - S02E02 - Beta.nfo"]
    assert paths["imdb-scores"] == ["Solaris (1972).nfo", "Some Show - S01E02 - Two.nfo", "tvshow.nfo"]
    assert paths["show-nfos"] == ["tvshow.nfo"]
    assert paths["film-nfos"] == ["Unknown.Film.nfo"]
    m = plan["manual"]
    assert [x["season"] for x in m["seasons"]] == [2]
    assert sorted(x["path"].rsplit("/", 1)[-1] for x in m["numbers"]) == [
        "Some Show - S01E03 - Two.mkv", "Some Show - S02E05 - Extra.mkv", "Some.Show.S10E-1.mkv"]
    assert [x["path"] for x in m["films"]] == ["Film/Mystery/Mystery.mkv"] and "isn't certain" in m["films"][0]["why"]


def test_fixes_apply_and_can_be_put_back(env):
    tmp, health, plan = env
    before = {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file() and "TV" in p.parts or "Film" in p.parts and p.is_file()}
    result = health.apply(plan, ["leftovers", "empty-films", "episode-nfos", "imdb-scores", "film-nfos", "show-nfos"])
    assert result["failed"] == [] and result["done"] == {"leftovers": 1, "empty-films": 1, "episode-nfos": 4, "imdb-scores": 3,
                                                         "film-nfos": 1, "show-nfos": 1}
    assert ET.parse(tmp / "Film" / "Unknown Film" / "Unknown.Film.nfo").getroot().findtext("title") == "Unknown Film"
    assert (tmp / "Film" / "Unknown Film" / "poster.jpg").exists() and (tmp / "TV" / "Other Show (2019)" / "tvshow.nfo").exists()
    s1 = tmp / "TV" / "Some Show" / "Season 01"
    nfo = ET.parse(s1 / "Some Show - S01E01 - One.nfo").getroot()
    assert nfo.findtext("title") == "One" and nfo.findtext("ratings/rating/value") == "7.1"  # IMDb's S01E01
    assert (s1 / "Some Show - S01E01 - One-thumb.jpg").read_bytes() == b"img"
    two = ET.fromstring((s1 / "Some Show - S01E02 - Two.nfo").read_text(encoding="utf-8").split("?>", 1)[1])
    assert [(r.get("name"), r.get("default")) for r in two.find("ratings")] == [("imdb", "true"), ("tvdb", "false")]
    assert not (s1 / "Downloaded from site.txt").exists() and not (tmp / "Film" / "Empty (2001)").exists()

    health.journal.undo(result["run"])
    after = {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file() and "TV" in p.parts or "Film" in p.parts and p.is_file()}
    assert after == before


def test_weekly_refresh_keeps_scores_health_added(env):
    tmp, health, plan = env
    health.apply(plan, ["imdb-scores"])
    nfo = tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E02 - Two.nfo"
    assert "7.2" in nfo.read_text(encoding="utf-8")
    refresh = health.scores
    summary = refresh.run()  # the same datasets: nothing changes, and the added score stays
    assert summary["updated"] == 0 and "7.2" in nfo.read_text(encoding="utf-8")


def test_choosing_a_film_turns_the_question_into_a_fix(env, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from muthur.web import Config, create_app

    tmp, _, _ = env
    for k, v in {"MUTHUR_CONFIG": tmp / "config", "MUTHUR_DOWNLOADS": tmp / "dl", "MUTHUR_TV": tmp / "TV", "MUTHUR_FILM": tmp / "Film",
                 "MUTHUR_QUARANTINE": tmp / "_q", "TMDB_READ_TOKEN": "x"}.items():
        monkeypatch.setenv(k, str(v))
    client = TestClient(create_app(Config(dotenv=False), tmdb_factory=lambda token, path: FakeTmdb()))
    client.post("/api/fixes/check")
    for _ in range(200):
        if not client.get("/api/jobs/current").json()["running"]:
            break
        time.sleep(0.05)
    assert client.get("/api/fixes").json()["manual"]["films"]["count"] == 1
    r = client.post("/api/fixes/choose", json={"kind": "movie", "path": "Film/Mystery/Mystery.mkv", "tmdbId": 61})
    assert r.status_code == 200, r.text
    assert r.json()["fixes"] == {"film-nfos": 1}
    after = client.get("/api/fixes").json()
    assert after["manual"]["films"]["count"] == 0 and after["fixes"]["film-nfos"]["count"] == 2

    # "The number is right": the episode named after TMDB's S01E02 is taken as S01E03 and gets its NFO.
    path = "TV/Some Show/Season 01/Some Show - S01E03 - Two.mkv"
    q = next(x for x in after["manual"]["numbers"]["items"] if x["path"] == path)
    assert q["tmdb"] == 7 and q["show"] == "Some Show" and not q.get("noNumber")
    r = client.post("/api/fixes/trust", json={"path": path})
    assert r.status_code == 200, r.text
    now = client.get("/api/fixes").json()
    assert path not in [x["path"] for x in now["manual"]["numbers"]["items"]]
    assert "TV/Some Show/Season 01/Some Show - S01E03 - Two.nfo" in [x["path"] for x in now["fixes"]["episode-nfos"]["sample"]]
