"""A show folder that is a film (6 Nov: 'Micro Men (2009)', a one-off TV film matched to the series 'Mountain Men'):
Health asks about the match, and 'It's a film' moves the video to Film."""
import xml.etree.ElementTree as ET

from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)

from muthur.rename import follow_in_kodi


class Tmdb(FakeTmdb):
    def tv(self, i):
        if i == 9:
            return {"id": 9, "name": "Mountain Men", "first_air_date": "2012-05-31", "seasons": [{"season_number": 1, "episode_count": 10}]}
        if i == 10:
            return {"id": 10, "name": "Micro Machines", "first_air_date": "2009-01-01", "seasons": [{"season_number": 1, "episode_count": 2}]}
        return super().tv(i)

    def movie_full(self, i):
        if i == 77:
            return {"id": 77, "title": "Micro Men", "original_title": "Micro Men", "original_language": "en", "release_date": "2009-10-08",
                    "poster_path": "/mm.jpg", "backdrop_path": "/mb.jpg", "imdb_id": "tt1527186", "images": {"logos": []}}
        return super().movie_full(i)


def micro_men(tmp, health):
    folder = tmp / "TV" / "Micro Men (2009)"
    write(folder / "tvshow.nfo", '<tvshow><title>Mountain Men</title><uniqueid type="tmdb">9</uniqueid></tvshow>')
    write(folder / "Micro.Men.2009.DVDRip.XviD-NoGRP.avi", "video")
    write(folder / "Micro.Men.2009.DVDRip.XviD-NoGRP.en.srt", "subs")
    write(folder / "season01-poster.jpg")
    health.tmdb = Tmdb()
    return folder


def test_a_match_nothing_like_the_folder_is_a_question(env):  # noqa: F811
    tmp, health, _ = env
    micro_men(tmp, health)
    plan = health.check(health.index.build())
    q = next(x for x in plan["manual"]["shows"] if x["path"] == "TV/Micro Men (2009)")
    assert q["doubt"] and q["tmdb"] == 9 and q["show"] == "Mountain Men" and "nothing like" in q["why"]
    assert q["video"] == "TV/Micro Men (2009)/Micro.Men.2009.DVDRip.XviD-NoGRP.avi"
    # Nothing else is asked or fixed about it while the match is in doubt (its episodes would be another show's).
    everything = [x for k in plan["fixes"].values() for x in k] + [x for k in plan["manual"].values() for x in k]
    assert [x["path"] for x in everything if x["path"].startswith("TV/Micro Men")] == ["TV/Micro Men (2009)"]
    # "It is Mountain Men": the question doesn't come back.
    health.store.put("health.matchOk", ["TV/Micro Men (2009)"])
    plan = health.check(health.index.build())
    assert not [x for x in plan["manual"]["shows"] if x["path"] == "TV/Micro Men (2009)"]
    # Another show chosen: a 'show-rematch' fix to it.
    health.store.put("library.rematch", {"Micro Men (2009)": 10})
    plan = health.check(health.index.build())
    fix = next(x for x in plan["fixes"]["show-rematch"] if x["path"] == "TV/Micro Men (2009)")
    assert fix["from"] == 9 and fix["to"] == 10 and fix["label"] == "Micro Men (2009): Micro Machines (2009), not Mountain Men (2012)"


def test_its_a_film_moves_it_to_film_and_can_be_put_back(env):  # noqa: F811
    tmp, health, _ = env
    folder = micro_men(tmp, health)
    before = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file() and "_q" not in p.parts and p.suffix != ".db")
    run = health.journal.start("library")
    new = health.to_film(run, "TV/Micro Men (2009)/Micro.Men.2009.DVDRip.XviD-NoGRP.avi", 77)
    assert new == "Film/Micro Men (2009)/Micro Men (2009).avi"
    film = tmp / "Film" / "Micro Men (2009)"
    assert (film / "Micro Men (2009).avi").read_text() == "video" and (film / "Micro Men (2009).en.srt").read_text() == "subs"
    assert ET.parse(film / "Micro Men (2009).nfo").getroot().findtext("title") == "Micro Men"
    assert (film / "Micro Men (2009)-poster.jpg").exists() and (film / "Micro Men (2009)-fanart.jpg").exists()
    assert not folder.exists() and any((tmp / "_q").rglob("tvshow.nfo"))  # the other show's NFO and art: quarantine
    health.journal.finish(run, {})
    health.journal.undo(run)
    after = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file() and "_q" not in p.parts and p.suffix != ".db")
    assert after == before


def test_a_film_that_was_an_episode_drops_the_episode_entry():
    class Kodi:
        def __init__(self):
            self.calls = []

        def source_prefix(self, name):
            return {"TV": "smb://nas/TV/", "Film": "smb://nas/Film/"}[name]

        def check(self):
            return {"connected": True}

        def scan_and_wait(self, folder, limit=300, waited=None):
            return True

        def call(self, method, params=None):
            self.calls.append((method, params))
            if method == "VideoLibrary.GetMovies":
                return {"movies": [{"movieid": 40, "file": "smb://nas/Film/Micro Men (2009)/Micro Men (2009).avi", "playcount": 0, "resume": {}}]}
            return "OK"

    k = Kodi()
    before = {"tv/micro men (2009)/micro.men.avi": {"kind": "episode", "kodiid": 40, "playcount": 1, "lastplayed": "2025-01-01 20:00:00",
                                                    "resume": 0, "total": 0}}
    r = follow_in_kodi(k, [("TV/Micro Men (2009)/Micro.Men.avi", "Film/Micro Men (2009)/Micro Men (2009).avi")],
                       {"TV": "/data/TV", "Film": "/data/Film"}, before)
    assert r == {"followed": 1, "problems": []}
    assert ("VideoLibrary.SetMovieDetails", {"movieid": 40, "playcount": 1, "lastplayed": "2025-01-01 20:00:00"}) in k.calls
    assert ("VideoLibrary.RemoveEpisode", {"episodeid": 40}) in k.calls  # same number, but an episode: it goes
