"""IMDb datasets, scores in NFOs, and the weekly refresh of NFOs muthur wrote."""
import gzip
import os
import xml.etree.ElementTree as ET

import pytest

from muthur import nfo_write
from muthur.imdb import Imdb
from muthur.journal import Journal
from muthur.scores import ScoreRefresh, changed, with_imdb
from muthur.store import Store

EPISODES = """tconst\tparentTconst\tseasonNumber\tepisodeNumber
tt101\ttt100\t1\t1
tt102\ttt100\t1\t2
tt103\ttt100\t1\t3
tt201\ttt200\t1\t1
tt104\ttt100\t\\N\t\\N
"""
RATINGS = """tconst\taverageRating\tnumVotes
tt100\t8.4\t41000
tt101\t7.9\t1200
tt102\t8.6\t1500
tt103\t9.1\t2100
tt201\t5.0\t10
tt900\t7.7\t300000
tt999\t6.0\t5
"""


@pytest.fixture
def imdb(tmp_path):
    files = {}
    for name, body in (("title.episode.tsv.gz", EPISODES), ("title.ratings.tsv.gz", RATINGS)):
        path = tmp_path / name
        path.write_bytes(gzip.compress(body.encode()))
        files[name] = path
    store = Store(str(tmp_path / "muthur.db"))
    i = Imdb(store, base="", opener=lambda url: open(files[url], "rb"))
    i.refresh({"tt100"}, {"tt900"})
    return i


def test_only_library_rows_are_kept(imdb):
    assert imdb.counts() == {"episodes": 4, "ratings": 5}  # tt100's episodes (one without numbers); not tt200, tt999
    assert imdb.rating("tt900") == (7.7, 300000)
    assert imdb.rating("tt999") is None
    assert not imdb.due()


def test_episode_score_needs_matching_season_counts(imdb):
    assert imdb.episode("tt100", 1, 2, 3) == (8.6, 1500)
    assert imdb.episode("tt100", 1, 2, 4) is None  # TMDB counts 4 in that season: the numbering differs
    assert imdb.episode("tt100", 2, 1, 3) is None


def test_imdb_is_the_default_rating():
    nfo = nfo_write.episode_nfo("Show", 1, {"episode_number": 2, "name": "Two", "vote_average": 7.0, "vote_count": 12, "id": 5}, 7,
                                imdb=(8.6, 1500))
    ratings = ET.fromstring(nfo.split(b"-->", 1)[1]).find("ratings")
    assert [(r.get("name"), r.get("default")) for r in ratings] == [("imdb", "true"), ("themoviedb", None)]
    plain = nfo_write.episode_nfo("Show", 1, {"episode_number": 2, "name": "Two", "vote_average": 7.0, "vote_count": 12, "id": 5}, 7)
    assert ET.fromstring(plain.split(b"-->", 1)[1]).find("ratings/rating").get("default") == "true"


def test_small_changes_are_not_rewritten():
    assert not changed((8.6, 1500), (8.62, 1600))
    assert changed((8.6, 1500), (8.7, 1500))
    assert changed((8.6, 1500), (8.6, 1700))
    assert changed(None, (8.6, 1500))
    assert changed((8.6, 1500), None)


def _episode_nfo(imdb_score=None):
    return nfo_write.episode_nfo("Some Show", 1, {"episode_number": 2, "name": "Two", "vote_average": 7.0, "vote_count": 12, "id": 502},
                                 7, imdb=imdb_score).decode()


def test_with_imdb_keeps_the_rest_of_the_file():
    text = _episode_nfo()
    new = with_imdb(text, (8.6, 1500))
    assert new.replace(_ratings_of(new), "") == text.replace(_ratings_of(text), "")
    root = ET.fromstring(new.split("-->", 1)[1])
    assert root.find("ratings/rating").get("name") == "imdb" and root.findtext("ratings/rating/value") == "8.6"
    assert with_imdb(new, (8.6, 1510)) is None


def _ratings_of(text):
    start = text.index("  <ratings>")
    return text[start:text.index("</ratings>") + len("</ratings>\n")]


class FakeTmdb:
    def tv(self, tv_id):
        return {"id": tv_id, "external_ids": {"imdb_id": "tt100"}}

    def tv_season(self, tv_id, season):
        return {"episodes": [{"id": 500 + n, "episode_number": n} for n in (1, 2, 3)]}


def test_refresh_updates_muthur_nfos_and_can_be_put_back(imdb, tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    season = tv / "Some Show (2021)" / "Season 01"
    season.mkdir(parents=True)
    film.mkdir()
    # A Sonarr-style NFO: no IMDb ID, so muthur finds it through the show's TMDB ID.
    (tv / "Some Show (2021)" / "tvshow.nfo").write_text('<tvshow><title>Some Show</title><uniqueid type="tmdb">7</uniqueid></tvshow>')
    ours, mapped, foreign = season / "Some Show (2021) - S01E02.nfo", season / "Some Show (2021) - S01E19.nfo", season / "other.nfo"
    ours.write_text(_episode_nfo(), encoding="utf-8", newline="")
    mapped.write_text(_episode_nfo().replace("<episode>2</episode>", "<episode>19</episode>"), encoding="utf-8", newline="")
    foreign.write_text("<episodedetails><season>1</season><episode>3</episode></episodedetails>")
    journal = Journal(imdb.store)
    run = journal.start("apply")
    for p in (ours, mapped, foreign):
        journal.record(run, "x", "write", None, str(p))
    before = ours.read_text(encoding="utf-8")

    refresh = ScoreRefresh(imdb.store, journal, imdb, FakeTmdb(), str(tv), str(film), str(tmp_path / "backups"))
    assert refresh.library_ids() == ({"tt100"}, set())
    summary = refresh.run()
    assert summary["updated"] == 1 and summary["checked"] == 3

    root = ET.fromstring(ours.read_text(encoding="utf-8").split("-->", 1)[1])
    assert root.findtext("ratings/rating/value") == "8.6"  # IMDb's S01E02
    assert "imdb" not in mapped.read_text(encoding="utf-8")  # filed under another number: no IMDb score
    assert "ratings" not in foreign.read_text()  # not written by muthur: left alone

    scores_run = next(r for r in journal.runs() if r["kind"] == "scores")
    assert [o["op"] for o in journal.ops(scores_run["id"])] == ["update"]
    journal.undo(scores_run["id"])
    assert ours.read_text(encoding="utf-8") == before
