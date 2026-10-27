"""Missing artwork (27 Oct): every file Kodi shows that isn't there, from TMDB or fanart.tv, whoever wrote the NFO;
and the subtitles inside a download, copied out when it is imported."""
import pytest
from test_apply import env as apply_env  # noqa: F401  (the Apply fixture)
from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)

from muthur import player
from muthur.fanart import best
from muthur.health import Health
from muthur.index import Index
from muthur.journal import Journal


def test_thumbnail_beside_another_tools_nfo(env):  # noqa: F811
    tmp, health, plan = env
    art = {x["path"]: x for x in plan["fixes"]["artwork"]}
    # S01E02 has an NFO from another tool and no thumbnail: before, only a missing NFO brought one along.
    x = art["TV/Some Show/Season 01/Some Show - S01E02 - Two-thumb.jpg"]
    assert (x["from"], x["src"], x["nfo"]) == ("tmdb", "/s12.jpg", "TV/Some Show/Season 01/Some Show - S01E02 - Two.nfo")
    # Episodes without an NFO get theirs with it ('episode-nfos'); the questioned one gets none.
    assert not any("S01E01" in p or "S01E03" in p for p in art)
    result = health.apply(plan, ["artwork"])
    thumb = tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E02 - Two-thumb.jpg"
    assert result["failed"] == [] and thumb.read_bytes() == b"img"
    health.journal.undo(result["run"])
    assert not thumb.exists()


class ArtTmdb(FakeTmdb):
    def tv_full(self, i):
        return {**super().tv_full(i), "backdrop_path": "/b.jpg", "external_ids": {"tvdb_id": 70},
                "seasons": [{"season_number": 1, "episode_count": 3, "poster_path": "/s1.jpg"}],
                "images": {"logos": [{"file_path": "/l.png", "iso_639_1": "en", "vote_average": 5}]}}

    def movie_full(self, i):
        return {"id": i, "title": "A Film", "backdrop_path": None, "images": {"logos": []}}


class FakeFanart:
    def get(self, kind, item_id):
        if kind == "tv" and item_id == 70:
            return {"tvbanner": [{"url": "https://assets.fanart.tv/b-de.jpg", "lang": "de", "likes": "9"},
                                 {"url": "https://assets.fanart.tv/b-en.jpg", "lang": "en", "likes": "1"}],
                    "seasonbanner": [{"url": "https://assets.fanart.tv/sb.jpg", "lang": "en", "likes": "1", "season": "2"}]}
        if kind == "movies" and item_id == 50:
            return {"moviebackground": [{"url": "https://assets.fanart.tv/bg.jpg", "lang": "", "likes": "3"}],
                    "moviedisc": [{"url": "https://assets.fanart.tv/disc.png", "lang": "en", "likes": "2"}]}
        return {}

    def image(self, url):
        return b"fan " + url.encode()


@pytest.fixture
def art_env(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    show = tv / "Some Show"
    write(show / "tvshow.nfo", '<tvshow><title>Some Show</title><uniqueid type="tmdb">7</uniqueid></tvshow>')
    write(show / "fanart.jpg")  # there already: never offered again
    write(show / "Season 01" / "Some Show - S01E01 - One.mkv")
    write(show / "Season 01" / "Some Show - S01E01 - One.nfo", "<episodedetails><title>One</title></episodedetails>")
    write(show / "Season 01" / "Some Show - S01E01 - One-thumb.jpg")
    write(film / "A Film (1999)" / "A Film (1999).mkv")
    write(film / "A Film (1999)" / "A Film (1999).nfo", '<movie><title>A Film</title><year>1999</year><uniqueid type="tmdb">50</uniqueid></movie>')
    from muthur.imdb import Imdb
    from muthur.store import Store
    store = Store(str(tmp_path / "muthur.db"))
    index = Index(store, str(tv), str(film))
    health = Health(store, Journal(store), Imdb(store, base=""), ArtTmdb(), index, str(tv), str(film), str(tmp_path / "_q"),
                    str(tmp_path / "backups"), FakeFanart())
    return tmp_path, health, health.check(index.build())


def test_show_season_and_film_art_from_tmdb_then_fanart(art_env):
    tmp, health, plan = art_env
    art = {x["path"]: (x["from"], x["src"]) for x in plan["fixes"]["artwork"]}
    assert art == {
        "TV/Some Show/clearlogo.png": ("tmdb", "/l.png"),  # TMDB first...
        "TV/Some Show/banner.jpg": ("fanart.tv", "https://assets.fanart.tv/b-en.jpg"),  # ...fanart.tv for what TMDB lacks, English first
        "TV/Some Show/season01-poster.jpg": ("tmdb", "/s1.jpg"),  # season 2's banner isn't asked: the library has no season 2
        "Film/A Film (1999)/fanart.jpg": ("fanart.tv", "https://assets.fanart.tv/bg.jpg"),  # TMDB has no backdrop for it
        "Film/A Film (1999)/discart.png": ("fanart.tv", "https://assets.fanart.tv/disc.png"),
    }
    result = health.apply(plan, ["artwork"])
    assert result["failed"] == [] and result["done"]["artwork"] == 5
    assert (tmp / "Film" / "A Film (1999)" / "discart.png").read_bytes() == b"fan https://assets.fanart.tv/disc.png"
    assert (tmp / "TV" / "Some Show" / "season01-poster.jpg").read_bytes() == b"img"
    assert (tmp / "TV" / "Some Show" / "fanart.jpg").read_text() == "x"  # left as it was


def test_without_fanart_keys_only_tmdb_art(art_env, tmp_path):
    _, health, _ = art_env
    plain = Health(health.store, health.journal, health.imdb, ArtTmdb(), health.index, *health.roots.values(), health.quarantine, health.backups)
    paths = {x["path"] for x in plain.check(health.index.build())["fixes"]["artwork"]}
    assert paths == {"TV/Some Show/clearlogo.png", "TV/Some Show/season01-poster.jpg"}


class FindTmdb(ArtTmdb):
    def find(self, external_id, source):
        return {"movie_results": [{"id": 50}]} if (external_id, source) == ("tt50", "imdb_id") else {}


def test_a_film_known_only_by_its_imdb_id_gets_its_artwork(art_env):
    """27 Oct: a film NFO with only IMDb's ID got no poster or artwork fixes; TMDB maps the ID exactly."""
    tmp, health, _ = art_env
    write(tmp / "Film" / "A Film (1999)" / "A Film (1999).nfo", '<movie><title>A Film</title><year>1999</year><uniqueid type="imdb">tt50</uniqueid></movie>')
    found = Health(health.store, health.journal, health.imdb, FindTmdb(), health.index, *health.roots.values(), health.quarantine,
                   health.backups, FakeFanart())
    paths = {x["path"] for x in found.check(health.index.build())["fixes"]["artwork"]}
    assert {"Film/A Film (1999)/fanart.jpg", "Film/A Film (1999)/discart.png"} <= paths


def test_best_fanart_image():
    images = [{"url": "https://assets.fanart.tv/fr.jpg", "lang": "fr", "likes": "50"},
              {"url": "https://assets.fanart.tv/none.jpg", "lang": "00", "likes": "2"},
              {"url": "https://assets.fanart.tv/en-1.jpg", "lang": "en", "likes": "1"},
              {"url": "https://assets.fanart.tv/en-7.jpg", "lang": "en", "likes": "7"}]
    assert best(images) == "https://assets.fanart.tv/en-7.jpg"
    assert best(images[:2]) == "https://assets.fanart.tv/none.jpg"
    assert best([{"url": "https://example.com/x.jpg", "lang": "en"}]) is None  # only fanart.tv's own servers
    seasons = [{"url": "https://assets.fanart.tv/all.jpg", "lang": "en", "season": "all"}, {"url": "https://assets.fanart.tv/s0.jpg", "lang": "en", "season": "0"}]
    assert best(seasons, 0) == "https://assets.fanart.tv/s0.jpg" and best(seasons, 1) is None


def test_import_copies_the_english_subtitles_out(apply_env, monkeypatch):  # noqa: F811
    tmp, applier, journal, show, film = apply_env
    applier.tmp = str(tmp / "tmp")
    monkeypatch.setattr(player, "embedded", lambda full: [{"index": 2, "lang": "en", "title": "", "forced": False, "sdh": False}]
                        if full.endswith("Een Film (1999).mkv") else [])
    monkeypatch.setattr(player, "extract", lambda full, chosen, tmp, progress=None: {name: b"1\n00:00:01,000 --> 00:00:02,000\nHi\n" for _, name in chosen})
    result = applier.apply([film])
    srt = tmp / "Film" / "Een Film (1999)" / "Een Film (1999).en.srt"
    assert result["applied"] == 1 and srt.exists()
    journal.undo(result["run"])
    assert not srt.exists()


def test_import_without_a_tmp_folder_leaves_subtitles_inside(apply_env, monkeypatch):  # noqa: F811
    tmp, applier, journal, show, film = apply_env
    monkeypatch.setattr(player, "embedded", lambda full: pytest.fail("not read without a tmp folder"))
    assert applier.apply([film])["applied"] == 1
