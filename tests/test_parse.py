"""Parser tests. Names are made up but follow patterns seen in real libraries."""
import pytest

from muthur.parse import parse_episode, parse_movie, parse_show_folder, clean


def ep(*parts):
    return parse_episode(list(parts))


def test_standard_episode():
    p = ep("Some Show", "Season 02", "Some.Show.S02E05.1080p.WEB.h264-GRP.mkv")
    assert (p.season, p.episodes, p.flags) == (2, [5], [])
    assert not p.blocked


def test_multi_episode():
    p = ep("Some Show", "Season 01", "Some Show - S01E01-E02 - Pilot.mkv")
    assert p.episodes == [1, 2]


def test_site_prefix_is_stripped():
    assert clean("www.SomeSite.org    -    Some.Show.S01E03.mkv") == "Some.Show.S01E03.mkv"
    p = ep("Some Show", "www.SomeSite.org - Some Show 2013 S01E03 Title 720p WEB-DL.mkv")
    assert (p.season, p.episodes) == (1, [3])


def test_broken_rename_is_blocked_not_read_as_episode_1():
    p = ep("Some Show", "Season 10", "Some Show S10E-1 (2003) - 480p - 3060.mkv")
    assert p.episodes == []
    assert "broken-episode-number" in p.flags and p.blocked


def test_broken_negative_season():
    p = ep("Some Show (2011)", "Season 01", "Some Show Part3 S-1E-1 - GRP - - 720p.mkv")
    assert "broken-episode-number" in p.flags


def test_implausible_episode_number():
    p = ep("Some Show", "Season 04", "Some Show S04E204 (2004) - SD.avi")
    assert "implausible-episode-number" in p.flags and p.blocked


@pytest.mark.parametrize("name", [
    "[Group] Some Anime - 01 [BD 720p AAC] [32D3798A].mkv",
    "[Group] Some Anime - 02v2 [BD 720p AAC] [1461B2FF].mkv",
])
def test_fansub_absolute_numbering(name):
    p = ep("Some Anime", name)
    assert "absolute-number" in p.flags
    assert p.absolute in (1, 2)
    assert not p.blocked


def test_ep_prefix_absolute():
    p = ep("Some Anime (2006)", "Some anime - EP 12.mp4")
    assert p.episodes == [12]


def test_part_numbering_becomes_season_1():
    p = ep("Some Docuseries (2017)", "some.docuseries.2017.part03.bdrip.x264-grp.mkv")
    assert (p.season, p.episodes) == (1, [3])
    assert "part-number" in p.flags


def test_decimal_recap_episode_is_blocked():
    p = ep("Some Anime (2004)", "Season 01", "[Grp] Some Anime - 10.5 (BDRip 1080p) [x].mkv")
    assert "decimal-episode" in p.flags and p.blocked


def test_movie_inside_a_show_folder():
    p = ep("Some Title", "Season 1", "Some.Title.2010.1080p.BluRay.x264.mp4")
    assert "looks-like-movie" in p.flags and p.blocked


def test_extras_have_no_number_but_are_extras():
    p = ep("Some Show", "Some Show Rides Again", "Costumes Revisited.mkv")
    assert "no-episode-number" in p.flags


def test_episode_in_wrong_season_folder():
    p = ep("Some Show", "Season 1", "Some.Show.S03E01.1080p.WEB.h264-GRP.mkv")
    assert "season-folder-mismatch" in p.flags


def test_specials_folder():
    p = ep("Some Show", "Specials", "Some Show - S00E02 - Christmas.mkv")
    assert p.special and p.season == 0


def test_sample_detected():
    p = ep("Some Show", "Some.Show.S01E01.sample.mkv")
    assert p.sample


@pytest.mark.parametrize("folder, title, year", [
    ("30 Rock", "30 Rock", None),
    ("1971 The Year That Music Changed Everything", "1971 The Year That Music Changed Everything", None),
    ("Alone.Australia", "Alone Australia", None),
    ("Some Show (2019)", "Some Show", 2019),
    ("Station.Eleven", "Station Eleven", None),
    ("Blade Runner 2049", "Blade Runner 2049", None),  # a future year is part of the title
])
def test_show_folder_names_are_not_over_guessed(folder, title, year):
    f = parse_show_folder(folder)
    assert (f.title, f.year) == (title, year)


def test_show_folder_with_year_and_country():
    f = parse_show_folder("Some Show (2021)")
    assert (f.title, f.year) == ("Some Show", 2021)
    f = parse_show_folder("The Office (US)")
    assert (f.title, f.country) == ("The Office", "US")


def test_movie_folder_year_wins_when_file_has_none():
    p = parse_movie(["Some Film (1972)", "some.film.bluray.mkv"])
    assert (p.title.lower(), p.year) == ("some film", 1972)


def test_loose_release_name_movie():
    p = parse_movie(["Some.Film.2022.1080p.AMZN.WEB-DL.DDP5.1.H.264-GRP.mkv"])
    assert (p.title, p.year) == ("Some Film", 2022)
    assert p.quality["source"] == "Web"


@pytest.mark.parametrize("parts, title, year", [
    (["Back to the Future Part II (1989)", "x.mkv"], "Back to the Future Part II", 1989),
    (["Some Limited (2007)", "Some.Limited.2007.mkv"], "Some Limited", 2007),
    (["Harold and Maude (1971) 720p BRrip_grp (x)", "a.mkv"], "Harold and Maude", 1971),
    (["Some Film (2021) (1080p WEB-DL x265 Grp).mkv"], "Some Film", 2021),
    (["WALL-E.2008.1080p.BrRip.x264.GRP", "WALL-E.2008.1080p.BrRip.x264.GRP.mp4"], "WALL-E", 2008),
])
def test_movie_titles_are_not_trimmed(parts, title, year):
    p = parse_movie(parts)
    assert (p.title, p.year) == (title, year)


def test_movie_without_year_is_flagged():
    p = parse_movie(["Solitary.1080p.BluRay.x264-GRP.mkv"])
    assert "no-year" in p.flags


def test_movie_extras_and_samples():
    assert parse_movie(["Some Film (2023)", "Featurettes", "Editing.mkv"]).extra
    assert parse_movie(["Some.Film.1997.1080p", "Some.Film.1997.1080p.sample.mkv"]).sample
    assert parse_movie(["Some.Film.2018.DVDRip", "Sample", "some.film.2018.dvdrip.mkv"]).sample


def test_year_in_show_folder_is_not_a_season():
    p = ep("Some Anime (2006)", "Some anime - EP 10.mp4")
    assert p.season is None and p.absolute == 10


@pytest.mark.parametrize("folder, title, country", [
    ("Some Show US", "Some Show", "US"),
    ("Some Show UK", "Some Show", "GB"),
    ("Some Show (UK)", "Some Show", "GB"),
])
def test_country_suffix(folder, title, country):
    f = parse_show_folder(folder)
    assert (f.title, f.country) == (title, country)
