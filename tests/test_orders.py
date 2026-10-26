"""A show read by another TMDB order (an 'episode group', e.g. DVD order): its numbers stop being questions, and NFOs
keep the file's numbers while describing the episode TMDB means."""
import xml.etree.ElementTree as ET

from test_health import env  # noqa: F401  (the Health fixture)

DVD = {"id": "G1", "groups": [
    {"name": "Season 1", "order": 1, "episodes": [{"season_number": 1, "episode_number": n, "order": n - 1, "name": t}
                                                   for n, t in ((1, "One"), (2, "Two"), (3, "Three"))]},
    # DVD season 2 holds five episodes: TMDB's S02E01-02, then three it airs elsewhere.
    {"name": "Season 2", "order": 2, "episodes": [
        {"season_number": 2, "episode_number": 1, "order": 0, "name": "Alpha"}, {"season_number": 2, "episode_number": 2, "order": 1, "name": "Beta"},
        {"season_number": 1, "episode_number": 1, "order": 2, "name": "One"}, {"season_number": 1, "episode_number": 2, "order": 3, "name": "Two"},
        {"season_number": 1, "episode_number": 3, "order": 4, "name": "Extra"}]},
]}


def test_a_show_read_by_its_dvd_order(env):  # noqa: F811
    tmp, health, plan = env
    assert [x["season"] for x in plan["manual"]["seasons"]] == [2]  # TMDB's own order: season 2 doesn't fit
    health.tmdb.get = lambda path, max_age=None, **p: DVD if path == "/tv/episode_group/G1" else {}
    assert health.order_map("G1")[(2, 5)]["episode_number"] == 3

    health.store.put("library.orders", {"Some Show": "G1"})
    again = health.check(health.index.build())
    assert again["manual"]["seasons"] == []  # by the DVD order the season fits
    fix = next(x for x in again["fixes"]["episode-nfos"] if x["path"].endswith("S02E05 - Extra.nfo"))
    assert fix["aired"] == [1, 3] and (fix["season"], fix["episode"]) == (2, 5)
    result = health.apply({"fixes": {"episode-nfos": [fix]}}, ["episode-nfos"])
    assert result["failed"] == []
    nfo = ET.parse(tmp / "TV" / "Some Show" / "Season 02" / "Some Show - S02E05 - Extra.nfo").getroot()
    assert (nfo.findtext("season"), nfo.findtext("episode"), nfo.findtext("title")) == ("2", "5", "Three")  # TMDB's S01E03
