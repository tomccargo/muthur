"""GET /api/owned: what is on disk by TMDB and IMDb ID, for another app, behind its own read-only key (ARCHITECTURE.md §14)."""
import pytest
from fastapi.testclient import TestClient

from muthur.index import Index
from muthur.store import Store
from muthur.web import Config, create_app

KEY = "a-long-random-read-only-key"
SHOW_NFO = '<tvshow><title>Thrones</title><uniqueid type="tmdb">1399</uniqueid><uniqueid type="imdb">tt0944947</uniqueid></tvshow>'


@pytest.fixture
def lib(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    s1, s2 = tv / "Thrones (2011)" / "Season 01", tv / "Thrones (2011)" / "Season 02"
    s1.mkdir(parents=True)
    s2.mkdir(parents=True)
    (tv / "Thrones (2011)" / "tvshow.nfo").write_text(SHOW_NFO)
    for name in ("Thrones - S01E01 - One.mkv", "Thrones - S01E02E03 - Two.mkv", "Thrones.S01E04.sample.mkv", "Thrones.S01E-1.mkv"):
        (s1 / name).write_bytes(b"v")
    (s2 / "Thrones - S02E01 - Again.mkv").write_bytes(b"v")
    # The same show in a second folder: listed once, its episodes put together.
    (tv / "Thrones (copy)").mkdir()
    (tv / "Thrones (copy)" / "tvshow.nfo").write_text(SHOW_NFO)
    (tv / "Thrones (copy)" / "Thrones - S01E05 - Five.mkv").write_bytes(b"v")
    (tv / "No Idea").mkdir()  # no NFO, no ID: nothing could match it
    (tv / "No Idea" / "No Idea - S01E01.mkv").write_bytes(b"v")
    for folder, nfo in (("The Matrix (1999)", '<movie><title>The Matrix</title><uniqueid type="tmdb">603</uniqueid>'
                                              '<uniqueid type="imdb">tt0133093</uniqueid></movie>'),
                        ("Solaris (1972)", '<movie><title>Solaris</title><uniqueid type="imdb">tt0069293</uniqueid></movie>')):
        (film / folder).mkdir(parents=True)
        (film / folder / f"{folder}.mkv").write_bytes(b"f" * 10)
        (film / folder / f"{folder}.nfo").write_text(nfo)
    return tmp_path


def _client(lib, monkeypatch, key: str | None = KEY, auth: bool = True, indexed: bool = True) -> TestClient:
    for k, v in {"MUTHUR_CONFIG": lib / "config", "MUTHUR_DOWNLOADS": lib / "dl", "MUTHUR_TV": lib / "TV", "MUTHUR_FILM": lib / "Film",
                 "MUTHUR_WEB": lib / "no-web"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setenv("MUTHUR_AUTH", "1" if auth else "0")
    if key is None:
        monkeypatch.delenv("MUTHUR_OWNED_KEY", raising=False)
    else:
        monkeypatch.setenv("MUTHUR_OWNED_KEY", key)
    if indexed:  # the index as a library scan leaves it, before the app starts
        (lib / "config").mkdir(exist_ok=True)
        store = Store(str(lib / "config" / "muthur.db"))
        store.save_snapshot("library", Index(store, str(lib / "TV"), str(lib / "Film")).build())
    return TestClient(create_app(Config(dotenv=False)))


def test_off_without_a_key(lib, monkeypatch):
    c = _client(lib, monkeypatch, key=None, auth=False)
    assert c.get("/api/owned", headers={"Authorization": f"Bearer {KEY}"}).status_code == 404
    c = _client(lib, monkeypatch, key="  ", auth=False)  # a blank key in .env is no key
    assert c.get("/api/owned", headers={"Authorization": "Bearer "}).status_code == 404


def test_only_the_key_opens_it_even_with_the_sign_in_on(lib, monkeypatch):
    c = _client(lib, monkeypatch)
    assert c.get("/api/status").status_code == 401  # the UI still asks to sign in
    r = c.get("/api/owned")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    for wrong in ("Bearer nope", f"Basic {KEY}", KEY, f"Bearer {KEY}x"):
        assert c.get("/api/owned", headers={"Authorization": wrong}).status_code == 401
    assert c.get("/api/owned", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    assert c.get("/api/owned", headers={"Authorization": f"bearer {KEY}"}).status_code == 200  # the scheme is case-insensitive


def test_a_signed_in_browser_still_needs_the_key(lib, monkeypatch):
    c = _client(lib, monkeypatch)
    assert c.post("/api/auth/setup", json={"password": "a long password"}).status_code == 200
    assert c.get("/api/status").status_code == 200
    assert c.get("/api/owned").status_code == 401


def test_what_is_owned(lib, monkeypatch):
    body = _client(lib, monkeypatch).get("/api/owned", headers={"Authorization": f"Bearer {KEY}"}).json()
    # A sample and a damaged file don't count; a double episode counts as both.
    assert body["tv"] == [{"tmdb": 1399, "imdb": "tt0944947", "seasons": {"1": [1, 2, 3, 5], "2": [1]}}]
    assert sorted(body["film"], key=lambda f: f["imdb"]) == [{"tmdb": None, "imdb": "tt0069293"}, {"tmdb": 603, "imdb": "tt0133093"}]


def test_nothing_indexed_yet(lib, monkeypatch):
    body = _client(lib, monkeypatch, indexed=False).get("/api/owned", headers={"Authorization": f"Bearer {KEY}"}).json()
    assert body == {"tv": [], "film": []}
