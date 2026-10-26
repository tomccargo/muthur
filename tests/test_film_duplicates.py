"""Film duplicates that went unseen: release notes named like the NFO, a duplicates list older than the NFOs that
make two copies the same film, and Kodi's old entries for videos that moved."""
import os
import time

import pytest

from muthur.kodi_entries import extra, remove
from muthur.library import scan_film
from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)

NFO = '<movie>\n  <title>Solaris</title>\n  <year>1972</year>\n  <uniqueid type="imdb">tt900</uniqueid>\n</movie>\n'
NOTES = "RELEASE: Solaris.1972.HDRip.XviD-EVO\r\nRUNTiME: 2 h 47 min\r\n"


def _case_sensitive(tmp_path) -> bool:
    (tmp_path / "a.nfo").write_text("x")
    (tmp_path / "a.NFO").write_text("y")
    return len([n for n in os.listdir(tmp_path) if n.lower() == "a.nfo"]) == 2


def test_the_nfo_kodi_asks_for_wins_over_release_notes(tmp_path):
    if not _case_sensitive(tmp_path):
        pytest.skip("this file system doesn't tell 'x.nfo' from 'x.NFO' (the NAS does)")
    film = tmp_path / "Film"
    for d in ("Solaris.1972.HDRip-EVO", "Solaris.1972.HDRip-EVO[TGx]"):
        write(film / d / "Solaris.1972.HDRip-EVO.avi")
        write(film / d / "Solaris.1972.HDRip-EVO.NFO", NOTES)  # the release notes come first in a listing
        write(film / d / "Solaris.1972.HDRip-EVO.nfo", NFO)
    write(film / "Loose.2001.NFO", NOTES)
    write(film / "Loose.2001.nfo", NFO)
    write(film / "Loose.2001.mkv")
    for u in scan_film(str(film)):
        assert u.nfo.endswith(".nfo"), u.key


def test_release_notes_beside_the_nfo_are_a_leftover_and_the_copies_are_duplicates(env):  # noqa: F811
    tmp, health, _ = env
    (tmp / "probe").mkdir()
    if not _case_sensitive(tmp / "probe"):
        pytest.skip("this file system doesn't tell 'x.nfo' from 'x.NFO' (the NAS does)")
    folder = tmp / "Film" / "Solaris.1972.HDRip-EVO"
    write(folder / "Solaris.1972.HDRip-EVO.avi")
    write(folder / "Solaris.1972.HDRip-EVO.NFO", NOTES)
    write(folder / "Solaris.1972.HDRip-EVO.nfo", NFO)
    lib = health.index.build()
    plan = health.check(lib)
    assert {"path": "Film/Solaris.1972.HDRip-EVO/Solaris.1972.HDRip-EVO.NFO", "why": "release notes beside the NFO"} in plan["fixes"]["leftovers"]
    assert not any("HDRip" in x["path"] for x in plan["fixes"]["film-nfos"])  # it has an NFO: no fix that can only fail
    from muthur.duplicates import _film_groups
    assert [sorted(f["key"] for f in g) for g in _film_groups(lib["films"])] == [["Solaris (1972)", "Solaris.1972.HDRip-EVO"]]
    result = health.apply(plan, ["leftovers"])
    assert result["failed"] == [] and not (folder / "Solaris.1972.HDRip-EVO.NFO").exists()
    assert (folder / "Solaris.1972.HDRip-EVO.nfo").read_text(encoding="utf-8") == NFO


def test_a_health_check_looks_for_duplicates_again(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from muthur.web import Config, create_app

    tmp, _, _ = env
    for k, v in {"MUTHUR_CONFIG": tmp / "config", "MUTHUR_DOWNLOADS": tmp / "dl", "MUTHUR_TV": tmp / "TV", "MUTHUR_FILM": tmp / "Film",
                 "MUTHUR_QUARANTINE": tmp / "_q", "TMDB_READ_TOKEN": "x"}.items():
        monkeypatch.setenv(k, str(v))
    client = TestClient(create_app(Config(dotenv=False), tmdb_factory=lambda token, path: FakeTmdb()))

    def check():
        client.post("/api/fixes/check")
        for _ in range(200):
            if not client.get("/api/jobs/current").json()["running"]:
                break
            time.sleep(0.05)

    check()
    assert client.get("/api/duplicates").json()["groups"] == []
    # An NFO written since (by Health, or by hand) makes a second copy the same film: the next check finds it.
    write(tmp / "Film" / "Solaris.1972.720p" / "Solaris.1972.720p.mkv")
    write(tmp / "Film" / "Solaris.1972.720p" / "Solaris.1972.720p.nfo", NFO)
    check()
    groups = client.get("/api/duplicates").json()["groups"]
    assert [g["kind"] for g in groups] == ["film"] and len(groups[0]["copies"]) == 2
    assert client.get("/api/status").json()["duplicates"] == 1


# -- Kodi's old entries ----------------------------------------------------------------------------------------
PREFIX = "smb://nas/media/Film/"


def _item(kodiid, file, key="movie:imdb:tt900", playcount=0, resume=0.0, label="Solaris (1972)"):
    return {"key": key, "kind": "movie", "label": label, "kodiid": kodiid, "file": file, "playcount": playcount,
            "lastplayed": "2026-01-02 20:00:00" if playcount else None, "resume": resume, "total": 9000.0 if resume else 0.0}


def test_kodis_old_entries_are_found_and_only_those(tmp_path):
    film = tmp_path / "Film"
    write(film / "Solaris (1972)" / "Solaris (1972).mkv")
    write(film / "Moon (2009)" / "Moon (2009).mkv")
    write(film / "Moon.2009.1080p" / "Moon.2009.1080p.mkv")
    write(film / "Gone Too (1999)" / "x.txt")
    items = [
        _item(1, PREFIX + "Solaris.1972.HDRip/Solaris.1972.HDRip.mkv", playcount=2),  # before a rename Kodi never followed
        _item(2, PREFIX + "Solaris (1972)/Solaris (1972).mkv"),
        _item(3, PREFIX + "Solaris (1972)/Solaris (1972).mkv"),  # the same file twice
        _item(4, PREFIX + "Moon (2009)/Moon (2009).mkv", key="movie:imdb:tt1182345", label="Moon (2009)"),
        _item(5, PREFIX + "Moon.2009.1080p/Moon.2009.1080p.mkv", key="movie:imdb:tt1182345", label="Moon (2009)"),  # two copies: Duplicates'
        _item(6, PREFIX + "Gone Too (1999)/Gone Too (1999).mkv", key="movie:imdb:tt1", label="Gone Too (1999)"),  # gone, no other entry: stays
        _item(7, "smb://nas/other/Solaris.mkv"),  # not in the library's folders
    ]
    found = extra(items, {"Film": str(film)}, {"Film": PREFIX})
    assert [(x["kodiid"], x["stays"], x["why"]) for x in found] == [(1, 2, "its video is gone"), (3, 2, "the same video twice")]


class FakeKodi:
    def __init__(self, entries, connected=True):
        self.entries, self.connected, self.calls = entries, connected, []

    def check(self):
        return {"connected": self.connected}

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "VideoLibrary.GetMovies":
            return {"movies": []}
        if method == "VideoLibrary.GetEpisodes":
            return {"episodes": []}
        if method == "VideoLibrary.GetTVShows":
            return {"tvshows": []}
        e = self.entries.get(params["movieid"])
        if e is None:
            raise RuntimeError("Invalid params")
        if method == "VideoLibrary.GetMovieDetails":
            return {"moviedetails": dict(e)}
        if method == "VideoLibrary.SetMovieDetails":
            e.update({k: v for k, v in params.items() if k != "movieid"})
        elif method == "VideoLibrary.RemoveMovie":
            del self.entries[params["movieid"]]
        return "OK"


def test_an_old_entry_gives_its_watched_status_before_it_goes():
    kodi = FakeKodi({1: {"playcount": 2, "lastplayed": "2026-01-02 20:00:00", "resume": {"position": 0, "total": 0}},
                     2: {"playcount": 0, "lastplayed": "", "resume": {"position": 0, "total": 0}}})
    backups = []
    entry = {"path": "Film/Solaris.1972.HDRip/Solaris.1972.HDRip.mkv", "label": "Solaris (1972)", "kind": "movie", "kodiid": 1, "stays": 2}
    r = remove(kodi, [entry], backup=backups.append)
    assert r == {"done": 1, "failed": []} and backups == [[]]  # a watched backup first
    assert list(kodi.entries) == [2] and kodi.entries[2]["playcount"] == 2 and kodi.entries[2]["lastplayed"] == "2026-01-02 20:00:00"


def test_a_resume_point_moves_too_and_kodi_off_changes_nothing():
    kodi = FakeKodi({1: {"playcount": 0, "lastplayed": "", "resume": {"position": 1200.0, "total": 9000.0}},
                     2: {"playcount": 0, "lastplayed": "", "resume": {"position": 0, "total": 0}}})
    entry = {"path": "Film/a.mkv", "label": "A", "kind": "movie", "kodiid": 1, "stays": 2}
    assert remove(FakeKodi(dict(kodi.entries), connected=False), [entry])["failed"][0]["why"].startswith("Kodi is off")
    assert remove(kodi, [entry])["done"] == 1 and kodi.entries[2]["resume"] == {"position": 1200.0, "total": 9000.0}
