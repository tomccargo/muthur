"""Episodes muthur places itself where it is certain (26 Oct): a title that is one TMDB episode's only, anywhere in the
show (Blackadder Rides Again is S00E17), one library season holding the next TMDB seasons (Fate Zero 25 = 13 + 12),
and extras moved to the show's Extras folder."""
from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)


class MoreTmdb(FakeTmdb):
    """Some Show gets a special; 'Long Show' (9) has two seasons of two episodes at TMDB."""

    def tv(self, i):
        if i == 9:
            return {"id": 9, "name": "Long Show", "seasons": [{"season_number": 1, "episode_count": 2}, {"season_number": 2, "episode_count": 2}],
                    "external_ids": {"imdb_id": "tt900900"}}
        d = super().tv(i)
        if i == 7:
            d = {**d, "seasons": [{"season_number": 0, "episode_count": 1}, *d["seasons"]]}
        return d

    def tv_season(self, i, n):
        if i == 9:
            names = {1: ["Arrival", "Bargain"], 2: ["Crossing", "Departure"]}[n]
            return {"episodes": [{"id": 900 + 10 * n + k, "episode_number": k, "name": t} for k, t in enumerate(names, 1)]}
        if i == 7 and n == 0:
            return {"episodes": [{"id": 700, "episode_number": 1, "name": "The Christmas Special"}]}
        return super().tv_season(i, n)

    def tv_full(self, i):
        return {**self.tv(i), "first_air_date": "2021-01-01", "poster_path": "/p.jpg", "images": {"logos": []}}


def test_a_special_is_found_by_its_title(env):  # noqa: F811
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    write(tmp / "TV" / "Some Show" / "Holiday" / "The Christmas Special.mkv")  # no number at all
    plan = health.check(health.index.build())
    renames = {x["path"]: x["to"] for x in plan["fixes"]["renames"]}
    assert renames["TV/Some Show/Holiday/The Christmas Special.mkv"] == "Some Show - S00E01 - The Christmas Special.mkv"
    assert any(x["season"] == 0 and x["episode"] == 1 for x in plan["fixes"]["episode-nfos"])
    assert not any("Christmas" in q["path"] for q in plan["manual"]["numbers"])
    # The fixture's S01E03 named "Two": S01E02 "Two" holds that number already, so it stays a question.
    assert any(q["path"].endswith("S01E03 - Two.mkv") for q in plan["manual"]["numbers"])


def test_one_library_season_holding_two_tmdb_seasons_is_numbered_through(env):  # noqa: F811
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = tmp / "TV" / "Long Show"
    write(show / "tvshow.nfo", '<tvshow><title>Long Show</title><uniqueid type="tmdb">9</uniqueid></tvshow>')
    for n in range(1, 5):
        write(show / "Season 1" / f"Long Show - 1x{n:02d}.mkv")  # one season of four, as anime often come
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames["Long Show - 1x03.mkv"] == "Long Show - S02E01 - Crossing.mkv"
    assert renames["Long Show - 1x04.mkv"] == "Long Show - S02E02 - Departure.mkv"
    assert not [q for q in plan["manual"]["seasons"] if q["path"] == "TV/Long Show"]  # all placed: no season question


def test_extras_go_to_the_extras_folder(env):  # noqa: F811
    tmp, health, _ = env
    write(tmp / "TV" / "Some Show" / "Season 01" / "Hugh Laurie Interview.mkv")
    write(tmp / "TV" / "Some Show" / "Season 01" / "Hugh Laurie Interview.en.srt")
    plan = health.check(health.index.build())
    fix = next(x for x in plan["fixes"]["extras"] if "Interview" in x["path"])
    result = health.apply({"fixes": {"extras": [fix]}}, ["extras"])
    assert result["failed"] == []
    assert (tmp / "TV" / "Some Show" / "Extras" / "Hugh Laurie Interview.mkv").exists()
    assert (tmp / "TV" / "Some Show" / "Extras" / "Hugh Laurie Interview.en.srt").exists()  # its subtitles go along
    health.journal.undo(result["run"])
    assert (tmp / "TV" / "Some Show" / "Season 01" / "Hugh Laurie Interview.mkv").exists()


def test_a_special_beyond_the_count_leaves_the_season_alone(env):  # noqa: F811
    """Shameless UK's 'S02E11 Christmas Special' after TMDB's ten: episodes 1-10 are fixed, only the special is asked."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = tmp / "TV" / "Long Show"
    write(show / "tvshow.nfo", '<tvshow><title>Long Show</title><uniqueid type="tmdb">9</uniqueid></tvshow>')
    write(show / "Season 2" / "Long Show S02E01 720p.mkv")
    write(show / "Season 2" / "Long Show S02E02 720p.mkv")
    write(show / "Season 2" / "Long Show S02E03 Christmas Special 720p.mkv")
    plan = health.check(health.index.build())
    asked = [q["path"].rsplit("/", 1)[-1] for q in plan["manual"]["numbers"] if "Long Show" in q["path"]]
    assert asked == ["Long Show S02E03 Christmas Special 720p.mkv"]
    assert not [q for q in plan["manual"]["seasons"] if q["path"] == "TV/Long Show"]
    assert {x["episode"] for x in plan["fixes"]["episode-nfos"] if "Long Show" in x["path"]} == {1, 2}


def test_a_renumbered_episode_gets_its_nfo_rewritten(env):  # noqa: F811
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = tmp / "TV" / "Long Show"
    write(show / "tvshow.nfo", '<tvshow><title>Long Show</title><uniqueid type="tmdb">9</uniqueid></tvshow>')
    for n in range(1, 5):
        write(show / "Season 1" / f"Long Show - 1x{n:02d}.mkv")
    write(show / "Season 1" / "Long Show - 1x03.nfo", "<episodedetails><title>Old</title><season>1</season><episode>3</episode></episodedetails>")
    plan = health.check(health.index.build())
    fix = next(x for x in plan["fixes"]["episode-nfos"] if x["path"].endswith("1x03.nfo"))
    assert fix["replace"] and (fix["season"], fix["episode"]) == (2, 1)
    result = health.apply({"fixes": {"episode-nfos": [fix]}}, ["episode-nfos"])
    assert result["failed"] == [] and "<season>2</season>" in (show / "Season 1" / "Long Show - 1x03.nfo").read_text(encoding="utf-8")
    health.journal.undo(result["run"])
    assert "<title>Old</title>" in (show / "Season 1" / "Long Show - 1x03.nfo").read_text(encoding="utf-8")
