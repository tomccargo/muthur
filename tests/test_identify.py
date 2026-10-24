"""Identifier decisions against a fake TMDB."""
from muthur.identify import identify_movie, identify_show


def _hit(query, name):
    """Like TMDB: every word of the query appears in the name."""
    return all(w in name.lower().split() for w in query.lower().split())


class FakeTmdb:
    def __init__(self, tv=(), movies=()):
        self._tv = {t["id"]: t for t in tv}
        self._movies = {m["id"]: m for m in movies}

    def search_tv(self, query, year=None):
        return [t for t in self._tv.values() if _hit(query, t["name"])
                and (year is None or t["first_air_date"].startswith(str(year)))]

    def tv(self, i):
        return self._tv[i]

    def search_movie(self, query, year=None):
        return [m for m in self._movies.values() if _hit(query, m["title"])
                and (year is None or m["release_date"].startswith(str(year)))]

    def movie(self, i):
        return self._movies[i]


def show(i, name, date, seasons, country="US", pop=20):
    return {"id": i, "name": name, "original_name": name, "first_air_date": date, "popularity": pop,
            "origin_country": [country], "seasons": [{"season_number": n, "episode_count": c} for n, c in seasons.items()],
            "external_ids": {"tvdb_id": i * 10, "imdb_id": f"tt{i:07d}"}}


def film(i, title, date, runtime, pop=10):
    return {"id": i, "title": title, "original_title": title, "release_date": date, "runtime": runtime, "popularity": pop}


SHOWS = FakeTmdb(tv=[
    show(1, "Ghosts", "2021-10-07", {1: 22, 2: 22, 3: 10, 4: 22, 5: 22}),
    show(2, "Ghosts", "2019-04-15", {1: 6, 2: 6, 3: 6, 4: 6, 5: 6}, country="GB"),
    show(3, "Lonely Planet Show", "2005-01-01", {1: 8}),
])


def test_year_in_name_gives_auto():
    m = identify_show(SHOWS, "Ghosts", year=2021, episodes={(5, 7)})
    assert m.status == "auto" and m.best.tmdb_id == 1


def test_episode_that_only_exists_on_one_show_decides():
    # S05E18 only exists on the 22-episode version, so the clash is resolved.
    m = identify_show(SHOWS, "Ghosts", episodes={(5, 18)})
    assert m.best.tmdb_id == 1
    assert not any("clash" in r for r in m.reasons)


def test_same_title_no_year_episode_on_both_goes_to_review():
    m = identify_show(SHOWS, "Ghosts", episodes={(1, 3)})
    assert m.status == "review"
    assert any("clash" in r for r in m.reasons)


def test_missing_episode_blocks_auto():
    m = identify_show(SHOWS, "Lonely Planet Show", episodes={(1, 9)})
    assert m.status == "review"


def test_typo_in_title_still_finds_the_show_but_needs_review():
    m = identify_show(SHOWS, "Lonely Planit Show", episodes={(1, 3)})
    assert m.best is not None and m.best.tmdb_id == 3
    assert m.status == "review"


def test_unique_show_without_year_is_auto():
    m = identify_show(SHOWS, "Lonely Planet Show", episodes={(1, 3), (1, 4)})
    assert m.status == "auto"


MOVIES = FakeTmdb(movies=[film(10, "Solaris", "1972-03-20", 167, pop=12), film(11, "Solaris", "2002-11-27", 99, pop=15)])


def test_movie_title_clash_without_year_is_review_even_if_runtime_points_one_way():
    m = identify_movie(MOVIES, "Solaris", duration_s=166 * 60)
    assert m.status == "review"
    assert m.best.tmdb_id == 10  # runtime still ranks the right one first


def test_movie_with_year_is_auto():
    m = identify_movie(MOVIES, "Solaris", year=1972, duration_s=166 * 60)
    assert m.status == "auto" and m.best.tmdb_id == 10


def test_no_candidates():
    assert identify_movie(MOVIES, "Nothing Like This").status == "none"


def test_runner_up_with_a_different_title_does_not_block_an_exact_match():
    src = FakeTmdb(tv=[show(20, "Sunny", "2024-07-10", {1: 10}, pop=5),
                       show(21, "Its Always Sunny Indeed", "2005-08-04", {1: 10}, pop=200)])
    m = identify_show(src, "Sunny", episodes={(1, 2)})
    assert m.status == "auto" and m.best.tmdb_id == 20


def test_year_off_by_one_is_still_found():
    src = FakeTmdb(movies=[film(30, "Mama", "1977-10-17", 88), film(31, "Mama", "2013-01-18", 100, pop=80)])
    m = identify_movie(src, "Mama", year=1976, duration_s=88 * 60)
    assert m.best.tmdb_id == 30
