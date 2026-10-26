"""Shows whose IMDb data isn't downloaded are found by Health, and subtitle languages are read from names."""
from muthur.index import _sub_langs
from test_health import env  # noqa: F401  (the Health fixture: one show with IMDb data, one without)


def test_subtitle_languages_come_from_the_names():
    files = ["x.mkv", "x.en.srt", "x.English.forced.srt", "x.nl.sdh.srt", "x.srt", "xy.fr.srt"]
    assert _sub_langs("x", files) == ["EN", "NL", "SUB"]  # EN once; 'xy.fr.srt' belongs to another video


def test_a_show_without_imdb_data_is_a_fix(env):  # noqa: F811
    _, health, plan = env
    have = health.imdb.shows_with_data()
    assert "tt100" in have
    missing = [x["path"] for x in plan["fixes"]["imdb-data"]]
    assert missing == ["TV/Other Show (2019)"]  # Some Show's data is there; Other Show's ID came from TMDB, its data didn't
