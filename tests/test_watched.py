"""The watched-status backup follows Kodi, stops on a wiped library, and restores without lowering anything."""
import pytest

from muthur.store import Store
from muthur.watched import Watched


class FakeKodi:
    def __init__(self):
        self.shows = [{"tvshowid": 1, "title": "The Office", "uniqueid": {"tmdb": "2316", "tvdb": "73244"}}]
        self.episodes = [{"episodeid": 10 + n, "tvshowid": 1, "season": 4, "episode": n, "playcount": 1 if n < 3 else 0,
                          "lastplayed": "2026-01-0%d 20:00:00" % n if n < 3 else "", "resume": {"position": 0, "total": 0},
                          "file": f"smb://nas/TV/The Office/S04E{n:02d}.mkv", "showtitle": "The Office"} for n in range(1, 5)]
        self.movies = [{"movieid": 7, "title": "Solaris", "year": 1972, "uniqueid": {"imdb": "tt0069293"}, "playcount": 0,
                        "lastplayed": "", "resume": {"position": 3600.0, "total": 9960.0}, "file": "smb://nas/Film/Solaris.mkv"}]
        self.sets = []

    def call(self, method, params=None):
        if method == "VideoLibrary.GetTVShows":
            return {"tvshows": self.shows}
        if method == "VideoLibrary.GetEpisodes":
            return {"episodes": self.episodes}
        if method == "VideoLibrary.GetMovies":
            return {"movies": self.movies}
        self.sets.append((method, params))
        return "OK"


@pytest.fixture
def env(tmp_path):
    return Watched(Store(str(tmp_path / "muthur.db"))), FakeKodi()


def test_follow_appends_only_changes(env):
    w, kodi = env
    first = w.follow(Watched.read_kodi(kodi))
    assert first["items"] == 5 and first["watched"] == 2 and first["changes"] == 5
    assert w.follow(Watched.read_kodi(kodi))["changes"] == 0
    kodi.episodes[2]["playcount"] = 1
    assert w.follow(Watched.read_kodi(kodi))["changes"] == 1
    latest = w.latest()
    assert latest["ep:tmdb:2316:4:3"]["playcount"] == 1
    assert latest["movie:imdb:tt0069293"]["resume"] == 3600.0


def test_a_wiped_library_pauses_the_backup(env):
    w, kodi = env
    w.follow(Watched.read_kodi(kodi))
    kodi.episodes, kodi.movies = kodi.episodes[:1], []  # Kodi suddenly knows 1 item instead of 5
    paused = w.follow(Watched.read_kodi(kodi))["paused"]
    assert "down from 5" in paused["why"]
    assert w.latest()["ep:tmdb:2316:4:2"]["playcount"] == 1  # the backup kept the last good state
    assert w.state()["paused"]
    w.follow(Watched.read_kodi(kodi), accept=True)
    assert not w.state()["paused"]


def test_many_items_turning_unwatched_pauses(env):
    w, kodi = env
    kodi.episodes = [{**kodi.episodes[0], "episodeid": 100 + n, "episode": n, "playcount": 1} for n in range(1, 31)]
    w.follow(Watched.read_kodi(kodi))
    for e in kodi.episodes:
        e["playcount"] = 0
    assert "30 items would turn unwatched" in w.follow(Watched.read_kodi(kodi))["paused"]["why"]


def test_restore_raises_play_counts_and_fills_resume_points(env):
    w, kodi = env
    w.follow(Watched.read_kodi(kodi))
    # A new Kodi database: nothing watched, the film's resume point gone, and the show now known by TVDB only.
    kodi.shows[0]["uniqueid"] = {"tvdb": "73244"}
    for e in kodi.episodes:
        e["playcount"], e["lastplayed"] = 0, ""
    kodi.movies[0]["resume"] = {"position": 0, "total": 0}
    plan = w.plan_restore(Watched.read_kodi(kodi))
    assert sorted((c["label"], c["what"]) for c in plan) == [
        ("Solaris (1972)", "resume"), ("The Office S04E01", "watched"), ("The Office S04E02", "watched")]
    result = Watched.restore(kodi, plan)
    assert result == {"done": 3, "failed": 0}
    assert ("VideoLibrary.SetEpisodeDetails", {"episodeid": 11, "playcount": 1, "lastplayed": "2026-01-01 20:00:00"}) in kodi.sets
    assert ("VideoLibrary.SetMovieDetails", {"movieid": 7, "resume": {"position": 3600.0, "total": 9960.0}}) in kodi.sets


def test_two_copies_of_one_episode_are_one_item(env):
    w, kodi = env
    copy = {**kodi.episodes[0], "episodeid": 99, "playcount": 0, "lastplayed": "", "file": "smb://nas/TV/The Office/copy.mkv"}
    kodi.episodes.append(copy)
    assert w.follow(Watched.read_kodi(kodi))["items"] == 5
    assert w.follow(Watched.read_kodi(kodi))["changes"] == 0  # the copies don't flip the state back and forth
    assert w.plan_restore(Watched.read_kodi(kodi)) == []  # one copy watched is enough


def test_restore_never_lowers(env):
    w, kodi = env
    w.follow(Watched.read_kodi(kodi))
    kodi.episodes[0]["playcount"] = 3  # watched again since the backup
    assert all(c["label"] != "The Office S04E01" for c in w.plan_restore(Watched.read_kodi(kodi)))
