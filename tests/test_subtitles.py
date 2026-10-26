"""Subtitles Kodi can't find: paired with their video, English and Dutch moved beside it, the rest set aside."""
import gzip
import io

import pytest
from test_health import EPISODES, RATINGS, FakeTmdb, write

from muthur.health import Health
from muthur.imdb import Imdb
from muthur.index import Index
from muthur.journal import Journal
from muthur.store import Store
from muthur.subtitles import language, plan


def test_language_comes_from_the_last_language_word():
    assert language("2_English") == "en" and language("x.nl.sdh") == "nl" and language("28.Days.Later.(2002).German") == "de"
    assert language("Community S02E09 - Y - SD ") is None and language(".eng.forced") == "en" and language(".hi") is None


@pytest.fixture
def lib(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    s1 = tv / "Bad Sisters" / "Season 1"
    write(s1 / "Bad.Sisters.S01E01.mkv")
    sub = s1 / "Subs" / "Bad.Sisters.S01E01"  # how RARBG ships them: Kodi never looks two folders down
    for n in ("2_English.srt", "3_English.srt", "10_German.srt", "@eaDir/2_English.srt"):
        write(sub / n)
    old, new = tv / "Community" / "Season 02", tv / "Community" / "Season 2"
    write(new / "Community S02E08 - Calligraphy.mkv")
    write(new / "Community S02E08 - Calligraphy.en.srt")  # Kodi finds this one
    write(new / "Community S02E09 - Conspiracy.mkv")
    write(old / "Community S02E08 - Calligraphy - SD.en.srt")  # its video moved to 'Season 2', which has English already
    write(old / "Community S02E09 - Conspiracy - SD .srt")  # its video moved, no subtitle there yet
    write(old / "Community S02E10 - Gone - SD.srt")  # no such episode any more
    days = film / "28 Days Later (2002)"
    write(days / "28 Days Later (2002).mkv")
    write(days / "Subtitles" / "28.Days.Later.(2002).English.srt")
    write(days / "Subtitles" / "28.Days.Later.(2002).German.srt")
    fav = film / "The Favourite (2018)"
    write(fav / "The Favourite (2018).mkv")
    write(fav / "Subs" / "the.favourite.2018.1080p.idx")  # one picture subtitle in two files: they move together
    write(fav / "Subs" / "the.favourite.2018.1080p.sub")
    dune = film / "Dune (2021)" / "Subs"
    for n in ("SDH.eng.HI.srt", "English.srt", "FORCED.eng.srt"):
        write(dune / n)
    write(film / "Dune (2021)" / "Dune (2021).mkv")
    write(film / "Fine (2001)" / "Fine (2001).mkv")
    write(film / "Fine (2001)" / "Fine (2001).en.srt")
    return tmp_path


def test_what_kodi_misses_is_paired_with_its_video(lib):
    fixes, left = plan("TV", str(lib / "TV"), "Bad Sisters")
    assert left == [] and len(fixes) == 1
    f = fixes[0]
    assert f["path"] == "TV/Bad Sisters/Season 1/Bad.Sisters.S01E01.mkv" and f["label"] == "Bad Sisters S01E01"
    assert f["move"] == [["TV/Bad Sisters/Season 1/Subs/Bad.Sisters.S01E01/2_English.srt", "TV/Bad Sisters/Season 1/Bad.Sisters.S01E01.en.srt"]]
    assert sorted(f["drop"]) == ["TV/Bad Sisters/Season 1/Subs/Bad.Sisters.S01E01/10_German.srt",
                                 "TV/Bad Sisters/Season 1/Subs/Bad.Sisters.S01E01/3_English.srt"]  # German, and a second English
    assert f["dirs"] == ["TV/Bad Sisters/Season 1/Subs/Bad.Sisters.S01E01", "TV/Bad Sisters/Season 1/Subs"]

    fixes, left = plan("TV", str(lib / "TV"), "Community")
    by = {f["label"]: f for f in fixes}
    assert by["Community S02E08"]["drop"] == ["TV/Community/Season 02/Community S02E08 - Calligraphy - SD.en.srt"]
    assert by["Community S02E09"]["move"] == [["TV/Community/Season 02/Community S02E09 - Conspiracy - SD .srt",
                                               "TV/Community/Season 2/Community S02E09 - Conspiracy.srt"]]
    assert left == [{"path": "TV/Community/Season 02/Community S02E10 - Gone - SD.srt", "why": "belongs to no video"}]

    (days,) = plan("Film", str(lib / "Film"), "28 Days Later (2002)")[0]
    assert days["move"] == [["Film/28 Days Later (2002)/Subtitles/28.Days.Later.(2002).English.srt", "Film/28 Days Later (2002)/28 Days Later (2002).en.srt"]]
    assert days["drop"] == ["Film/28 Days Later (2002)/Subtitles/28.Days.Later.(2002).German.srt"]
    (fav,) = plan("Film", str(lib / "Film"), "The Favourite (2018)")[0]
    assert [t for _, t in fav["move"]] == ["Film/The Favourite (2018)/The Favourite (2018).idx", "Film/The Favourite (2018)/The Favourite (2018).sub"]
    assert plan("Film", str(lib / "Film"), "Fine (2001)") == ([], [])
    (dune,) = plan("Film", str(lib / "Film"), "Dune (2021)")[0]  # forced is its own track; of two English the plain one stays
    assert [t.rsplit("/", 1)[1] for _, t in dune["move"]] == ["Dune (2021).en.srt", "Dune (2021).en.forced.srt"]
    assert dune["drop"] == ["Film/Dune (2021)/Subs/SDH.eng.HI.srt"]


def test_the_fix_moves_sets_aside_and_can_be_put_back(lib):
    store = Store(str(lib / "muthur.db"))
    files = {"title.episode.tsv.gz": EPISODES, "title.ratings.tsv.gz": RATINGS}
    imdb = Imdb(store, base="", opener=lambda url: io.BytesIO(gzip.compress(files[url].encode())))
    index = Index(store, str(lib / "TV"), str(lib / "Film"))
    health = Health(store, Journal(store), imdb, FakeTmdb(), index, str(lib / "TV"), str(lib / "Film"), str(lib / "_q"), str(lib / "backups"))
    before = sorted(str(p.relative_to(lib)) for p in lib.rglob("*") if p.is_file() and p.parts[len(lib.parts)] in ("TV", "Film"))
    checked = health.check(index.build())
    assert len(checked["fixes"]["subtitles"]) == 6
    result = health.apply(checked, ["subtitles", "leftovers"])
    assert result["failed"] == []
    s1 = lib / "TV" / "Bad Sisters" / "Season 1"
    assert (s1 / "Bad.Sisters.S01E01.en.srt").exists() and not (s1 / "Subs").exists()  # emptied, with its @eaDir, into quarantine
    assert (lib / "Film" / "28 Days Later (2002)" / "28 Days Later (2002).en.srt").exists()
    assert not (lib / "Film" / "28 Days Later (2002)" / "Subtitles").exists()
    assert health.check(index.build())["fixes"]["subtitles"] == []
    health.journal.undo(result["run"])
    after = sorted(str(p.relative_to(lib)) for p in lib.rglob("*") if p.is_file() and p.parts[len(lib.parts)] in ("TV", "Film"))
    assert after == before
