"""Library edits: change the match, the title and the poster, each one a run that can be put back."""
import xml.etree.ElementTree as ET

import pytest

from muthur.imdb import Imdb
from muthur.journal import Journal
from muthur.library_edit import LibraryEdit
from muthur.store import Store


class FakeTmdb:
    def tv_full(self, i):
        return {"id": i, "name": "Ghosts", "original_name": "Ghosts", "original_language": "en", "first_air_date": "2021-10-07",
                "poster_path": "/new.jpg", "external_ids": {"imdb_id": "tt11379026"}, "images": {"logos": []}}

    def movie_full(self, i):
        return {"id": i, "title": "Solaris", "original_title": "Солярис", "original_language": "ru", "release_date": "1972-03-20",
                "poster_path": "/sol.jpg", "images": {"logos": []}}

    def image(self, path, size):
        return f"IMG {path}".encode()

    def get(self, path, max_age=None, **params):
        return {"posters": [{"file_path": "/a.jpg", "iso_639_1": "en", "vote_count": 3}, {"file_path": "/b.jpg", "iso_639_1": None}]}


@pytest.fixture
def env(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    (tv / "Ghosts (2021)").mkdir(parents=True)
    (tv / "Ghosts (2021)" / "tvshow.nfo").write_text("<tvshow><title>Ghosts</title><uniqueid type=\"tmdb\">999</uniqueid></tvshow>")
    (tv / "Ghosts (2021)" / "poster.jpg").write_bytes(b"old poster")
    (film / "Solaris (1972)").mkdir(parents=True)
    (film / "Solaris (1972)" / "Solaris (1972).mkv").write_bytes(b"v")
    store = Store(str(tmp_path / "muthur.db"))
    journal = Journal(store)
    edit = LibraryEdit(store, journal, FakeTmdb(), Imdb(store), str(tv), str(film), str(tmp_path / "backups"))
    return tmp_path, edit, journal, store


def test_change_the_match_of_a_show_and_put_it_back(env):
    tmp, edit, journal, store = env
    nfo = tmp / "TV" / "Ghosts (2021)" / "tvshow.nfo"
    before = nfo.read_text()
    result = edit.match_show("Ghosts (2021)", 95396)
    root = ET.fromstring(nfo.read_text(encoding="utf-8").split("-->", 1)[1])
    assert root.find("uniqueid[@type='tmdb']").text == "95396"
    assert (tmp / "TV" / "Ghosts (2021)" / "poster.jpg").read_bytes() == b"IMG /new.jpg"
    assert store.tmdb_for_folder("tv", "Ghosts (2021)") == 95396  # remembered for the folder
    journal.undo(result["run"])
    assert nfo.read_text() == before and (tmp / "TV" / "Ghosts (2021)" / "poster.jpg").read_bytes() == b"old poster"


def test_a_film_without_an_nfo_gets_one(env):
    tmp, edit, journal, _ = env
    edit.match_film("Film/Solaris (1972)/Solaris (1972).mkv", None, "Film/Solaris (1972)/", 593)
    nfo = tmp / "Film" / "Solaris (1972)" / "Solaris (1972).nfo"
    assert ET.fromstring(nfo.read_text(encoding="utf-8").split("-->", 1)[1]).findtext("title") == "Solaris"  # not Latin script: the English title (the title rule)
    assert (tmp / "Film" / "Solaris (1972)" / "poster.jpg").exists()


def test_retitle_and_poster(env):
    tmp, edit, journal, _ = env
    edit.retitle("TV/Ghosts (2021)/tvshow.nfo", "Ghosts (US) & friends")
    assert "<title>Ghosts (US) &amp; friends</title>" in (tmp / "TV" / "Ghosts (2021)" / "tvshow.nfo").read_text()
    assert [p["path"] for p in edit.posters("tv", 95396)] == ["/a.jpg", "/b.jpg"]
    edit.set_poster("TV/Ghosts (2021)/poster.jpg", "/b.jpg")
    assert (tmp / "TV" / "Ghosts (2021)" / "poster.jpg").read_bytes() == b"IMG /b.jpg"
    with pytest.raises(ValueError):
        edit.set_poster("TV/Ghosts (2021)/poster.jpg", "https://evil.example/x.jpg")
    with pytest.raises(ValueError):
        edit.full("TV/../muthur.db")
