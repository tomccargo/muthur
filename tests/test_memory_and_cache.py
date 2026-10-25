"""The TMDB cache's expiry rules and the ID memory's cleanup."""
import shutil
import time

from muthur.memory import import_tv
from muthur.store import Store
from muthur.tmdb import DAY, Tmdb


# ---- TMDB cache ------------------------------------------------------------------

class FakeResponse:
    def __init__(self, body):
        self.status_code, self._body, self.headers = 200, body, {}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


def make_tmdb(tmp_path, answers):
    t = Tmdb("token", str(tmp_path / "cache.sqlite"))
    t.requests = []

    def fake_get(url, params=None, timeout=None):
        t.requests.append(url)
        return FakeResponse(answers(url))

    t.session.get = fake_get
    return t


def age_everything(t, seconds):
    t.db.execute("UPDATE cache SET fetched = fetched - ?", (seconds,))
    t.db.commit()


def test_running_show_is_refetched_after_a_day_but_a_finished_one_is_not(tmp_path):
    t = make_tmdb(tmp_path, lambda url: {"status": "Ended" if url.endswith("/1") else "Returning Series"})
    t.tv(1), t.tv(2)
    t.tv(1), t.tv(2)
    assert len(t.requests) == 2  # both cached
    age_everything(t, 2 * DAY)
    t.tv(1), t.tv(2)
    assert t.requests[2:] == ["https://api.themoviedb.org/3/tv/2"]  # only the running show


def test_season_with_recent_episodes_expires_and_old_season_does_not(tmp_path):
    today = time.strftime("%Y-%m-%d")

    def answers(url):
        if url.endswith("/season/1"):
            return {"episodes": [{"air_date": "2010-01-01"}, {"air_date": "2010-01-08"}]}
        return {"episodes": [{"air_date": today}, {"air_date": None}]}

    t = make_tmdb(tmp_path, answers)
    t.tv_season(5, 1), t.tv_season(5, 2)
    age_everything(t, 2 * DAY)
    t.tv_season(5, 1), t.tv_season(5, 2)
    assert t.requests[2:] == ["https://api.themoviedb.org/3/tv/5/season/2"]


def test_empty_search_expires_after_a_day(tmp_path):
    t = make_tmdb(tmp_path, lambda url: {"results": []})
    t.search_tv("Brand New Show")
    age_everything(t, 2 * DAY)
    t.search_tv("Brand New Show")
    assert len(t.requests) == 2


# ---- ID memory cleanup -------------------------------------------------------------

class FakeShows:
    SHOWS = {
        "Some Show": {"id": 11, "first_air_date": "2019-01-01", "tvdb": 110},
        "Other Show": {"id": 22, "first_air_date": "2015-01-01", "tvdb": 220},
    }

    def search_tv(self, query, year=None):
        return [{"id": v["id"], "name": k, "original_name": k, "first_air_date": v["first_air_date"], "popularity": 5,
                 "origin_country": ["US"]} for k, v in self.SHOWS.items() if k.lower() == query.lower()]

    def tv(self, i):
        name, v = next((k, v) for k, v in self.SHOWS.items() if v["id"] == i)
        return {"id": i, "name": name, "original_name": name, "first_air_date": v["first_air_date"],
                "seasons": [{"season_number": 1, "episode_count": 10}], "external_ids": {"tvdb_id": v["tvdb"]}}


def add_show(root, name, tmdb_id):
    d = root / name / "Season 01"
    d.mkdir(parents=True)
    (d / f"{name} - S01E01.mkv").write_bytes(b"x")
    (root / name / "tvshow.nfo").write_text(f'<tvshow><title>{name}</title><uniqueid type="tmdb">{tmdb_id}</uniqueid></tvshow>')


def test_learning_is_idempotent_and_forgets_removed_folders(tmp_path):
    tv = tmp_path / "TV"
    add_show(tv, "Some Show", 11)
    add_show(tv, "Other Show", 22)
    store = Store(str(tmp_path / "muthur.db"))

    first = import_tv(FakeShows(), str(tv), store)
    assert first["remembered"] == 2 and first["forgotten"] == 0
    assert [r["tmdb_id"] for r in store.lookup("tv", "Other Show")] == [22]

    again = import_tv(FakeShows(), str(tv), store)
    assert again == first  # nothing new, nothing lost
    assert store.alias_count("tv") == 2

    store.remember("tv", "Other Show", 22, 2015, "Other Show", "Other Show", "confirmed")  # chosen in Review
    shutil.rmtree(tv / "Other Show")
    store.remember("tv", "Gone Show", 33, 2001, "Gone Show", "Gone Show", "library")
    after = import_tv(FakeShows(), str(tv), store)
    assert after["forgotten"] == 1  # 'Gone Show' learned from the library, no longer there
    assert store.lookup("tv", "Gone Show") == []
    assert [r["source"] for r in store.lookup("tv", "Other Show")] == ["confirmed"]  # never dropped


def test_empty_tv_folder_does_not_wipe_the_memory(tmp_path):
    tv = tmp_path / "TV"
    add_show(tv, "Some Show", 11)
    store = Store(str(tmp_path / "muthur.db"))
    import_tv(FakeShows(), str(tv), store)
    shutil.rmtree(tv)
    tv.mkdir()  # an unmounted share looks like this
    assert import_tv(FakeShows(), str(tv), store)["forgotten"] == 0
    assert store.alias_count("tv") == 1


def test_confirmed_choice_is_not_downgraded_by_learning(tmp_path):
    store = Store(str(tmp_path / "muthur.db"))
    store.remember("tv", "Some Show", 11, 2019, "Some Show", "Some Show", "confirmed")
    store.remember("tv", "Some Show", 11, 2019, "Some Show", "Some Show (2019)", "library")
    [row] = store.lookup("tv", "Some Show")
    assert row["source"] == "confirmed" and row["folder"] == "Some Show (2019)"


def test_snapshot_lists_are_counted_without_loading_them(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    assert store.snapshot_count("duplicates", "$.groups") == 0
    store.save_snapshot("duplicates", {"at": 1, "groups": [{}, {}, {}]})
    store.save_snapshot("health", {"fixes": {"leftovers": [1, 2], "imdb-scores": [3], "show-nfos": []}})
    assert store.snapshot_count("duplicates", "$.groups") == 3
    assert store.snapshot_count("health", "$.fixes", each=True) == 3
