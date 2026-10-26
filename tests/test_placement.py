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


def test_a_shorter_name_for_one_tmdb_title_places_it(env):  # noqa: F811
    """26 Oct: Superstore's 'Election' is TMDB's 'Election Day': whole words of one title only are that episode. Never
    a part of a word ('Cross' isn't 'Crossing'), nor a generic name (27 Oct: Versailles' 'Episode 2' isn't 'Episode 24')."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = SpecialTmdb()
    show = tmp / "TV" / "Long Show"
    write(show / "tvshow.nfo", '<tvshow><title>Long Show</title><uniqueid type="tmdb">9</uniqueid></tvshow>')
    write(show / "Unsorted" / "Making the Cut.mkv")  # no number; whole words of 'Making the Cut: Season 1' (S00E01) only
    write(show / "Unsorted" / "Cross.mkv")
    write(show / "Unsorted" / "Making.mkv")  # one word of five: no evidence (27 Oct: Avatar's 'Aang')
    write(show / "Season 1" / "Long Show S01E01 - Episode 1.mkv")
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames["Making the Cut.mkv"] == "Long Show - S00E01 - Making the Cut - Season 1.mkv"
    assert "Cross.mkv" not in renames and "Making.mkv" not in renames
    assert renames.get("Long Show S01E01 - Episode 1.mkv", "").startswith("Long Show - S01E01")  # its own number, never a special


class SpecialTmdb(MoreTmdb):
    """'Long Show' also has a special named after its season, as Alone's 'Making the Cut: Season 3'."""

    def tv(self, i):
        d = super().tv(i)
        return {**d, "seasons": [{"season_number": 0, "episode_count": 1}, *d["seasons"]]} if i == 9 else d

    def tv_season(self, i, n):
        if i == 9 and n == 0:
            return {"episodes": [{"id": 990, "episode_number": 1, "name": "Making the Cut: Season 1"}]}
        return super().tv_season(i, n)


def _long(tmp):
    show = tmp / "TV" / "Long Show"
    write(show / "tvshow.nfo", '<tvshow><title>Long Show</title><uniqueid type="tmdb">9</uniqueid></tvshow>')
    return show


def test_one_episode_in_two_files_becomes_its_parts(env):  # noqa: F811
    """26 Oct (The Office's 'Fun Run (1)' and '(2)', TMDB's one 'Fun Run'): both get TMDB's number as Part 1 and 2,
    and the next file moves up to TMDB's number for it."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = _long(tmp)
    write(show / "Season 1" / "Long Show - S01E01 - Arrival (1).mkv")
    write(show / "Season 1" / "Long Show S01E02 - Arrival (2) - (2007) - SD.avi")  # the part in the middle, as The Office's
    write(show / "Season 1" / "Long Show - S01E03 - Bargain.mkv")
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames == {"Long Show - S01E01 - Arrival (1).mkv": "Long Show - S01E01 - Arrival (Part 1).mkv",
                       "Long Show S01E02 - Arrival (2) - (2007) - SD.avi": "Long Show - S01E01 - Arrival (Part 2).avi",
                       "Long Show - S01E03 - Bargain.mkv": "Long Show - S01E02 - Bargain.mkv"}
    nfo = next(x for x in plan["fixes"]["episode-nfos"] if x["path"].endswith("Arrival (2) - (2007) - SD.nfo"))
    assert (nfo["season"], nfo["episode"], nfo["title"]) == (1, 1, "Arrival (Part 2)")
    assert not [q for q in plan["manual"]["numbers"] + plan["manual"]["seasons"] if q["path"].startswith("TV/Long Show")]


def test_a_second_half_called_x_2_is_part_2(env):  # noqa: F811
    """27 Oct (Parks and Recreation: Sonarr's NFOs call the halves 'Galentine's Day' and 'Galentine's Day 2', TMDB has one
    'Galentine's Day')."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = _long(tmp)
    for n, t in ((1, "Arrival"), (2, "Arrival 2"), (3, "Bargain")):
        write(show / "Season 1" / f"Long Show S01E0{n}.mkv")
        write(show / "Season 1" / f"Long Show S01E0{n}.nfo", f"<episodedetails><title>{t}</title><season>1</season><episode>{n}</episode></episodedetails>")
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames == {"Long Show S01E01.mkv": "Long Show - S01E01 - Arrival (Part 1).mkv", "Long Show S01E02.mkv": "Long Show - S01E01 - Arrival (Part 2).mkv",
                       "Long Show S01E03.mkv": "Long Show - S01E02 - Bargain.mkv"}


def test_another_tools_nfo_title_places_an_untitled_file(env):  # noqa: F811
    """26 Oct (Parks and Recreation: names without titles, Sonarr's NFOs with them)."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = _long(tmp)
    write(show / "Season 2" / "Long Show S02E03.mkv")  # beyond season 2's two, within the show's four
    write(show / "Season 2" / "Long Show S02E03.nfo", "<episodedetails><title>Crossing</title><season>2</season><episode>3</episode></episodedetails>")
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames["Long Show S02E03.mkv"] == "Long Show - S02E01 - Crossing.mkv"


def test_a_special_kept_in_its_season_is_found(env):  # noqa: F811
    """26 Oct (Alone's 'S03E00 - Making the Cut' is TMDB's 'Making the Cut: Season 3', S00E04)."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = SpecialTmdb()
    show = _long(tmp)
    write(show / "Season 1" / "Long Show S01E00 - Making the Cut.mkv")
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames["Long Show S01E00 - Making the Cut.mkv"] == "Long Show - S00E01 - Making the Cut - Season 1.mkv"


def test_a_double_file_of_one_tmdb_episode_gets_its_single_number(env):  # noqa: F811
    """27 Oct (Parks' 'S06E01E02', TMDB's one 'London'): the file becomes S01E01 alone, its NFO one episode's, so the next
    file can take E02 without two files claiming it."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = _long(tmp)
    write(show / "Season 1" / "Long Show S01E01E02 - Arrival.mkv")
    write(show / "Season 1" / "Long Show S01E01E02 - Arrival.nfo", "<episodedetails><title>Arrival</title><season>1</season><episode>1</episode></episodedetails>"
          "<episodedetails><title>Arrival</title><season>1</season><episode>2</episode></episodedetails>")
    write(show / "Season 1" / "Long Show S01E03 - Bargain.mkv")
    plan = health.check(health.index.build())
    renames = {x["path"].rsplit("/", 1)[-1]: x["to"] for x in plan["fixes"]["renames"] if "Long Show" in x["path"]}
    assert renames == {"Long Show S01E01E02 - Arrival.mkv": "Long Show - S01E01 - Arrival.mkv", "Long Show S01E03 - Bargain.mkv": "Long Show - S01E02 - Bargain.mkv"}
    assert any(x["path"].endswith("S01E01E02 - Arrival.nfo") and x.get("replace") for x in plan["fixes"]["episode-nfos"])


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


def test_an_impossible_number_is_a_damaged_name(env):  # noqa: F811
    """'S01E968' in a show of five episodes: asked which episode it is, not 'season 1 numbered up to 968'."""
    tmp, health, _ = env
    write(tmp / "TV" / "Some Show" / "Season 01" / "Some Show S01E968 (2017) - 1080p.mkv")
    plan = health.check(health.index.build())
    q = next(q for q in plan["manual"]["numbers"] if "E968" in q["path"])
    assert q.get("noNumber")
    assert not [s for s in plan["manual"]["seasons"] if s["path"] == "TV/Some Show" and s["season"] == 1]


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
    again = health.check(health.index.build())  # its NFO says TMDB's number now: only the rename is left
    assert not [x for x in again["fixes"]["episode-nfos"] if x["path"].endswith("1x03.nfo")]
    assert [x for x in again["fixes"]["renames"] if x["path"].endswith("1x03.mkv")]
    health.journal.undo(result["run"])
    assert "<title>Old</title>" in (show / "Season 1" / "Long Show - 1x03.nfo").read_text(encoding="utf-8")


def test_broken_names_get_the_seasons_gaps_as_suggestions(env):  # noqa: F811
    """27 Oct (Doc Martin's 'S04E204 (2004)'..'S04E210'): as many broken names as episodes nobody holds: suggested in name
    order, for the reader to confirm. 'Part2' in a name suggests episode 2 (The Kennedys)."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = MoreTmdb()
    show = _long(tmp)
    write(show / "Season 2" / "Long Show S02E902 (2003) - 480p.mkv")
    write(show / "Season 2" / "Long Show S02E901 (2003) - 480p.mkv")
    write(show / "Season 2" / "Long Show S02E902 (2003) - 480p.nfo", "<episodedetails><title>Crossing</title><season>2</season><episode>1</episode></episodedetails>")
    write(show / "Season 1" / "Long Show Part2 S-1E-1.mkv")
    plan = health.check(health.index.build())
    hints = {q["path"].rsplit("/", 1)[-1]: q.get("suggest") for q in plan["manual"]["numbers"] if "Long Show" in q["path"]}
    # E902's NFO (another tool's) says E01, a gap: that first; E901 fills what is left (27 Oct: Art of Japanese Life)
    assert hints["Long Show S02E902 (2003) - 480p.mkv"]["episode"] == 1 and hints["Long Show S02E901 (2003) - 480p.mkv"]["episode"] == 2
    assert (hints["Long Show Part2 S-1E-1.mkv"]["season"], hints["Long Show Part2 S-1E-1.mkv"]["episode"]) == (1, 2)


def test_files_the_reader_calls_extras_go_to_extras(env):  # noqa: F811
    """27 Oct (Jiskefet's DVD compilations): 'It's an extra' takes them out of the questions, into the Extras folder."""
    tmp, health, _ = env
    write(tmp / "TV" / "Some Show" / "Een Pak.m4v")
    asked = health.check(health.index.build())
    assert any(q["path"] == "TV/Some Show/Een Pak.m4v" for q in asked["manual"]["numbers"])
    health.store.put("health.extras", ["TV/Some Show/Een Pak.m4v"])
    plan = health.check(health.index.build())
    assert not any(q["path"] == "TV/Some Show/Een Pak.m4v" for q in plan["manual"]["numbers"])
    assert next(x for x in plan["fixes"]["extras"] if x["path"] == "TV/Some Show/Een Pak.m4v")["to"] == "Extras/Een Pak.m4v"
