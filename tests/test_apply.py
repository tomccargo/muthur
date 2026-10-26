"""Apply and undo against temporary folders and a fake TMDB."""
import os
import xml.etree.ElementTree as ET

import pytest

from muthur.apply import Applier
from muthur.journal import Journal
from muthur.store import Store


class FakeTmdb:
    def tv_full(self, i):
        return {"id": i, "name": "Some Show", "original_name": "Some Show", "first_air_date": "2021-01-01",
                "overview": "A plot.", "status": "Returning Series", "genres": [{"name": "Comedy"}],
                "networks": [{"name": "CBS"}], "vote_average": 7.6, "vote_count": 900, "poster_path": "/p.jpg",
                "backdrop_path": "/b.jpg", "external_ids": {"imdb_id": "tt0000007", "tvdb_id": 70},
                "aggregate_credits": {"cast": [{"name": "An Actor", "roles": [{"character": "Ghost"}], "profile_path": "/a.jpg"}]},
                "images": {"logos": [{"file_path": "/l.png", "iso_639_1": "en", "vote_average": 5}]}}

    def tv_season(self, i, n):
        return {"poster_path": "/s.jpg", "episodes": [{"id": 501, "episode_number": 2, "name": "The Second One",
                                                       "air_date": "2021-01-08", "overview": "Things happen.",
                                                       "still_path": "/e.jpg", "vote_average": 7.1, "vote_count": 30,
                                                       "crew": [{"job": "Director", "name": "A Director"}]}]}

    def movie_full(self, i):
        return {"id": i, "title": "Some Film", "original_title": "Een Film", "release_date": "1999-05-01",
                "runtime": 100, "imdb_id": "tt0000009", "poster_path": "/mp.jpg", "backdrop_path": None,
                "credits": {"cast": [], "crew": [{"job": "Director", "name": "D"}]}, "images": {"logos": []}}

    def image(self, path, size):
        return f"IMG {path} {size}".encode() if path else None


@pytest.fixture
def env(tmp_path):
    dl, tv, film = tmp_path / "complete", tmp_path / "TV", tmp_path / "Film"
    for d in (dl, tv, film):
        d.mkdir()
    rel = dl / "Some.Show.S01E02.1080p.WEB"
    rel.mkdir()
    (rel / "some.show.s01e02.mkv").write_bytes(b"video" * 1000)
    (rel / "some.show.s01e02.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    (rel / "Downloaded from site.txt").write_text("junk")
    (dl / "Some.Film.1999.mkv").write_bytes(b"film" * 1000)
    store = Store(str(tmp_path / "muthur.db"))
    journal = Journal(store)
    applier = Applier(FakeTmdb(), journal, str(dl), str(tv), str(film), str(tmp_path / "_muthur-quarantine"))
    show_item = {"id": "Some.Show.S01E02.1080p.WEB", "status": "ready", "kind": "tv", "title": "Some Show", "tmdb_id": 7,
                 "files": [{"source": "Some.Show.S01E02.1080p.WEB/some.show.s01e02.mkv", "library": "TV", "season": 1,
                            "episodes": [2], "target": "Some Show (2021)/Season 01/Some Show (2021) - S01E02 - The Second One.mkv"}]}
    film_item = {"id": "Some.Film.1999.mkv", "status": "ready", "kind": "movie", "title": "Een Film", "tmdb_id": 9,
                 "files": [{"source": "Some.Film.1999.mkv", "library": "Film", "target": "Een Film (1999)/Een Film (1999).mkv"}]}
    return tmp_path, applier, journal, show_item, film_item


def snapshot(root):
    return sorted(os.path.relpath(os.path.join(d, n), root) for d, dirs, names in os.walk(root) for n in names + dirs)


def test_apply_moves_and_writes_kodi_files(env):
    tmp, applier, journal, show, film = env
    result = applier.apply([show, film])
    assert result["applied"] == 2, result

    ep = tmp / "TV" / "Some Show (2021)" / "Season 01" / "Some Show (2021) - S01E02 - The Second One"
    assert (ep.parent / (ep.name + ".mkv")).read_bytes() == b"video" * 1000
    assert (ep.parent / (ep.name + ".en.srt")).exists()  # the subtitle followed the video
    nfo = ET.parse(ep.parent / (ep.name + ".nfo")).getroot()
    assert nfo.tag == "episodedetails" and nfo.findtext("title") == "The Second One" and nfo.findtext("season") == "1"
    assert (ep.parent / (ep.name + "-thumb.jpg")).read_bytes() == b"IMG /e.jpg original"

    show_dir = tmp / "TV" / "Some Show (2021)"
    tvshow = ET.parse(show_dir / "tvshow.nfo").getroot()
    assert tvshow.find("uniqueid[@type='tmdb']").text == "7" and tvshow.find("uniqueid[@type='imdb']").text == "tt0000007"
    assert tvshow.find("ratings/rating[@name='themoviedb']/value").text == "7.6"
    for name in ("poster.jpg", "fanart.jpg", "clearlogo.png", "season01-poster.jpg"):
        assert (show_dir / name).exists(), name

    movie = ET.parse(tmp / "Film" / "Een Film (1999)" / "Een Film (1999).nfo").getroot()
    assert movie.findtext("title") == "Een Film" and movie.findtext("director") == "D"
    assert (tmp / "Film" / "Een Film (1999)" / "poster.jpg").exists()
    assert not (tmp / "Film" / "Een Film (1999)" / "fanart.jpg").exists()  # TMDB had none

    # The emptied download folder (only junk left) went to quarantine; the downloads folder is empty.
    assert os.listdir(tmp / "complete") == []
    quarantined = [p for p in snapshot(tmp / "_muthur-quarantine") if p.endswith(".txt")]
    assert quarantined and quarantined[0].endswith("Downloaded from site.txt")


def test_existing_target_stops_the_item_before_any_change(env):
    tmp, applier, journal, show, film = env
    target = tmp / "Film" / "Een Film (1999)"
    target.mkdir()
    (target / "Een Film (1999).mkv").write_bytes(b"already here")
    before = snapshot(tmp)
    result = applier.apply([film])
    assert result["applied"] == 0 and "already exists" in result["items"][0]["why"]
    assert snapshot(tmp) == before
    assert (target / "Een Film (1999).mkv").read_bytes() == b"already here"


def test_undo_puts_everything_back(env):
    tmp, applier, journal, show, film = env
    before = snapshot(tmp)
    run = applier.apply([show, film])["run"]
    assert snapshot(tmp) != before
    result = journal.undo(run)
    assert result["skipped"] == [] and result["undone"] > 0
    assert snapshot(tmp) == before  # same files, same places; created folders removed again
    assert journal.runs()[0]["undone"] is not None


def test_undo_leaves_a_file_that_was_changed_afterwards(env):
    tmp, applier, journal, show, film = env
    run = applier.apply([film])["run"]
    nfo = tmp / "Film" / "Een Film (1999)" / "Een Film (1999).nfo"
    nfo.write_text("<movie><title>edited by hand</title></movie>")
    result = journal.undo(run)
    assert any("changed after muthur wrote it" in s["why"] for s in result["skipped"])
    assert nfo.read_text().startswith("<movie><title>edited by hand")  # never deleted
    assert (tmp / "complete" / "Some.Film.1999.mkv").exists()  # the film itself did go back


def test_only_ready_items_are_applied(env):
    tmp, applier, journal, show, film = env
    show["status"] = "review"
    assert applier.apply([show])["applied"] == 0


def test_quarantine_says_what_and_why(env):
    tmp, applier, journal, show, film = env
    applier.apply([show])
    from muthur.quarantine import notes

    day = next((tmp / "_muthur-quarantine").iterdir()).name
    [n] = notes(str(tmp / "_muthur-quarantine"), day)
    assert n["to"] == "Some.Show.S01E02.1080p.WEB" and "after its video moved" in n["why"]


def test_a_subtitle_only_follows_its_own_video(env):
    tmp, applier, journal, show, film = env
    dl = tmp / "complete"
    (dl / "Some.Film.1999.en.srt").write_text("mine")
    (dl / "Some.Film.1999.forced.English.srt").write_text("mine too")
    (dl / "Some.Film.1999.Part.Two.2024.en.srt").write_text("the sequel's")
    (dl / "Some.Film.19990.en.srt").write_text("another film's")
    applier.apply([film])
    folder = tmp / "Film" / "Een Film (1999)"
    assert (folder / "Een Film (1999).en.srt").read_text() == "mine"
    assert (folder / "Een Film (1999).forced.English.srt").read_text() == "mine too"
    assert (dl / "Some.Film.1999.Part.Two.2024.en.srt").exists()  # same start, but a title and a year: another video's
    assert (dl / "Some.Film.19990.en.srt").exists()  # 'Some.Film.1999' + '0...' is another name


def test_subtitles_in_a_subs_folder_follow_the_film(env):
    tmp, applier, journal, show, film = env
    rel = tmp / "complete" / "Some.Film.1999.1080p"
    (rel / "Subs").mkdir(parents=True)
    (rel / "Some.Film.1999.1080p.mkv").write_bytes(b"film" * 1000)
    (rel / "Subs" / "2_English.srt").write_text("en")
    (rel / "Subs" / "3_Dutch.srt").write_text("nl")  # not needed: there is English
    (rel / "Subs" / "4_English.srt").write_text("en again")  # one per language
    (rel / "Subs" / "5_English [SDH].srt").write_text("en sdh")
    (rel / "Subs" / "6_English [Forced].srt").write_text("en forced")  # a forced track is its own
    (rel / "Subs" / "7_German.srt").write_text("de")  # not a language you keep
    item = {**film, "id": "Some.Film.1999.1080p",
            "files": [{"source": "Some.Film.1999.1080p/Some.Film.1999.1080p.mkv", "library": "Film", "target": "Een Film (1999)/Een Film (1999).mkv"}]}
    assert applier.apply([item])["applied"] == 1
    folder = tmp / "Film" / "Een Film (1999)"
    subs = sorted(p.name for p in folder.iterdir() if p.suffix == ".srt")
    assert subs == ["Een Film (1999).en.forced.srt", "Een Film (1999).en.srt"]
    assert (folder / "Een Film (1999).en.srt").read_text() == "en"
    assert not (tmp / "complete" / "Some.Film.1999.1080p").exists()  # the rest went to quarantine with the download's remains


def test_dutch_comes_along_only_without_english(env):
    tmp, applier, journal, show, film = env
    rel = tmp / "complete" / "Some.Film.1999.1080p"
    (rel / "Subs").mkdir(parents=True)
    (rel / "Some.Film.1999.1080p.mkv").write_bytes(b"film" * 1000)
    (rel / "Subs" / "3_Dutch.srt").write_text("nl")
    (rel / "Subs" / "7_German.srt").write_text("de")
    item = {**film, "id": "Some.Film.1999.1080p",
            "files": [{"source": "Some.Film.1999.1080p/Some.Film.1999.1080p.mkv", "library": "Film", "target": "Een Film (1999)/Een Film (1999).mkv"}]}
    assert applier.apply([item])["applied"] == 1
    assert sorted(p.name for p in (tmp / "Film" / "Een Film (1999)").iterdir() if p.suffix == ".srt") == ["Een Film (1999).nl.srt"]


def test_every_change_is_journalled_as_done_with_its_fingerprint(env):
    tmp, applier, journal, show, film = env
    run = applier.apply([film])["run"]
    ops = journal.ops(run)
    assert ops and all(o["status"] == "done" for o in ops)
    assert all(o["digest"] for o in ops if o["op"] in ("move", "write"))
    assert journal.counts([run])[run]["write"] == sum(o["op"] == "write" for o in ops)
