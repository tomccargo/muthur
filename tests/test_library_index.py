"""The library index and the Library API, against a small library in a temporary folder."""
import time

import pytest
from fastapi.testclient import TestClient

from muthur.index import Index
from muthur.store import Store
from muthur.web import Config, create_app

SHOW_NFO = '<tvshow><title>Some Show</title><year>2021</year><uniqueid type="tmdb">7</uniqueid><uniqueid type="imdb">tt100</uniqueid></tvshow>'
EP_NFO = ('<?xml version="1.0"?>\n<!-- written by muthur 0.6.0 from TMDB tv/7 season 1 -->\n<episodedetails><title>Two</title>'
          '<season>1</season><episode>2</episode><ratings><rating name="imdb" max="10" default="true"><value>8.6</value>'
          '<votes>1500</votes></rating></ratings></episodedetails>')


@pytest.fixture
def lib(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    s1 = tv / "Some Show (2021)" / "Season 01"
    s1.mkdir(parents=True)
    (tv / "Some Show (2021)" / "tvshow.nfo").write_text(SHOW_NFO)
    (tv / "Some Show (2021)" / "poster.jpg").write_bytes(b"jpg")
    (s1 / "Some Show (2021) - S01E01 - One.mkv").write_bytes(b"v1")
    (s1 / "Some Show (2021) - S01E02 - Two.mkv").write_bytes(b"v2")
    (s1 / "Some Show (2021) - S01E02 - Two.nfo").write_text(EP_NFO)
    (s1 / "Some.Show.S01E02.720p.mkv").write_bytes(b"dup")  # a second copy of S01E02
    (s1 / "Some Show (2021) - S01E09 - Gone.nfo").write_text("<episodedetails/>")  # its video is gone
    (s1 / "Downloaded from site.txt").write_text("junk")
    (tv / "Some Show (2021)" / "Season 01" / "Some.Show.S10E-1.mkv").write_bytes(b"broken")
    (film / "Solaris (1972)").mkdir(parents=True)
    (film / "Solaris (1972)" / "Solaris (1972).mkv").write_bytes(b"f" * 10)
    (film / "Solaris (1972)" / "Solaris (1972).nfo").write_text(
        '<movie><title>Solaris</title><year>1972</year><uniqueid type="imdb">tt0069293</uniqueid></movie>')
    return tmp_path


def test_index_reads_what_is_on_disk(lib):
    store = Store(str(lib / "muthur.db"))
    played = {"k": {"ids": '{"tmdb": "7"}', "season": 1, "episode": 2, "playcount": 3}}
    idx = Index(store, str(lib / "TV"), str(lib / "Film")).build(played)
    show = idx["shows"][0]
    assert show["ids"] == {"tmdb": "7", "imdb": "tt100"} and show["poster"] and show["year"] == 2021
    eps = {e["file"].rsplit("/", 1)[1]: e for e in show["episodes"]}
    two = eps["Some Show (2021) - S01E02 - Two.mkv"]
    assert two["imdb"] == [8.6, 1500] and two["rating"] == ["imdb", 8.6, 1500] and two["muthur"] and two["watched"] == 3
    assert not eps["Some Show (2021) - S01E01 - One.mkv"]["nfo"]
    assert eps["Some.Show.S10E-1.mkv"]["damaged"]
    assert sorted(show["loose"]) == ["Season 01/Downloaded from site.txt", "Season 01/Some Show (2021) - S01E09 - Gone.nfo"]
    assert idx["films"][0]["ids"] == {"imdb": "tt0069293"} and idx["films"][0]["title"] == "Solaris"


def test_library_api(lib, monkeypatch):
    for k, v in {"MUTHUR_CONFIG": lib / "config", "MUTHUR_DOWNLOADS": lib / "dl", "MUTHUR_TV": lib / "TV", "MUTHUR_FILM": lib / "Film"}.items():
        monkeypatch.setenv(k, str(v))
    client = TestClient(create_app(Config(dotenv=False)))
    assert client.get("/api/library").json()["at"] is None
    client.post("/api/library/scan")
    for _ in range(100):
        if not client.get("/api/jobs/current").json()["running"]:
            break
        time.sleep(0.05)
    data = client.get("/api/library").json()
    show = data["shows"][0]
    assert show["count"] == 4 and show["problems"] == {"noNfo": 3, "noScore": 3, "duplicates": 1, "damaged": 1, "loose": 2}
    detail = client.get("/api/library/show", params={"folder": "Some Show (2021)"}).json()
    assert sum(e["duplicate"] for e in detail["episodes"]) == 2
    assert client.get("/api/library/art", params={"path": "TV/Some Show (2021)/poster.jpg"}).content == b"jpg"
    for bad in ("TV/../muthur.db", "TV/Some Show (2021)/Season 01/Some Show (2021) - S01E02 - Two.nfo", "config/x.jpg"):
        assert client.get("/api/library/art", params={"path": bad}).status_code == 404
