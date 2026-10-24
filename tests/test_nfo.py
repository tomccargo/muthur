from muthur.nfo import parse_nfo_text


def test_kodi_tvshow_uniqueids():
    info = parse_nfo_text("""<?xml version="1.0" encoding="UTF-8"?>
<tvshow><title>Some Show</title><year>2002</year><id>79126</id>
<uniqueid type="tvdb" default="true">79126</uniqueid>
<uniqueid type="imdb">tt0306414</uniqueid>
<uniqueid type="tmdb">1438</uniqueid>
<uniqueid type="sonarr">12</uniqueid></tvshow>""")
    assert info.kind == "tvshow"
    assert info.ids == {"tvdb": "79126", "imdb": "tt0306414", "tmdb": "1438", "sonarr": "12"}
    assert (info.title, info.year) == ("Some Show", 2002)


def test_movie_streamdetails_duration_and_legacy_id():
    info = parse_nfo_text("""<movie><fileinfo><streamdetails><video>
<durationinseconds>6998</durationinseconds></video></streamdetails></fileinfo>
<title>Some Film</title><id>tt0078748</id><tmdbid>348</tmdbid></movie>""")
    assert info.duration_s == 6998
    assert info.ids == {"tmdb": "348", "imdb": "tt0078748"}


def test_url_nfo():
    info = parse_nfo_text("https://www.imdb.com/title/tt0111161/\r\n")
    assert not info.readable
    assert info.ids == {"imdb": "tt0111161"}


def test_scene_nfo_with_tmdb_link():
    info = parse_nfo_text("ASCII art...\n TMDB: https://www.themoviedb.org/movie/603-the-matrix \n")
    assert info.ids["tmdb"] == "603"
