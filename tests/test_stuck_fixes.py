"""Fixes that kept coming back: an empty NFO, an episode TMDB doesn't list, a show IMDb has no episodes for."""
import xml.etree.ElementTree as ET

from test_health import env, write  # noqa: F401  (the Health fixture)


def test_an_empty_nfo_is_rewritten_and_can_be_put_back(env):  # noqa: F811
    tmp, health, _ = env
    nfo = tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E01 - One.nfo"
    nfo.write_bytes(b"")  # some tools leave 0-byte NFOs: they tell Kodi nothing
    plan = health.check(health.index.build())
    path = "TV/Some Show/Season 01/Some Show - S01E01 - One.nfo"
    assert path in [x["path"] for x in plan["fixes"]["episode-nfos"]]
    assert path not in [x["path"] for x in plan["fixes"]["imdb-scores"]]  # no 'add a score' to nothing
    fix = next(x for x in plan["fixes"]["episode-nfos"] if x["path"] == path)
    result = health.apply({"fixes": {"episode-nfos": [fix]}}, ["episode-nfos"])
    assert result["failed"] == [] and ET.parse(nfo).getroot().findtext("title") == "One"
    health.journal.undo(result["run"])
    assert nfo.read_bytes() == b""


def test_an_episode_tmdb_doesnt_list_is_a_question_not_a_fix(env):  # noqa: F811
    tmp, health, _ = env
    write(tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E00 - Special.mkv")  # an OAV: TMDB has no S01E00
    plan = health.check(health.index.build())
    assert not any("S01E00" in x["path"] for x in plan["fixes"]["episode-nfos"])
    q = next(x for x in plan["manual"]["numbers"] if "S01E00" in x["path"])
    assert "TMDB has no S01E00" in q["why"]


def test_a_show_imdb_has_no_episodes_for_isnt_offered_again(env):  # noqa: F811
    _, health, plan = env
    assert [x["path"] for x in plan["fixes"]["imdb-data"]] == ["TV/Other Show (2019)"]
    health.store.put("imdb.asked", ["tt100", "tt800"])  # the last download asked for it, and IMDb had nothing
    assert health.check(health.index.build())["fixes"]["imdb-data"] == []


def test_a_double_episode_nfo_is_read_with_its_score():
    from muthur.nfo import parse_nfo_text

    two = ('<episodedetails>\n  <title>A Little Kiss (1)</title>\n  <season>5</season>\n  <episode>1</episode>\n  <ratings>\n'
           '    <rating name="imdb" max="10" default="true">\n      <value>8.5</value>\n      <votes>3469</votes>\n    </rating>\n'
           '  </ratings>\n</episodedetails>\n<episodedetails>\n  <title>A Little Kiss (2)</title>\n  <season>5</season>\n'
           '  <episode>2</episode>\n</episodedetails>\n')
    info = parse_nfo_text(two)  # one <episodedetails> per episode: two roots, as Kodi wants them
    assert info.readable and info.title == "A Little Kiss (1)" and info.ratings["imdb"] == (8.5, 3469)


def test_release_notes_in_the_nfos_place_make_way_for_a_real_nfo(env):  # noqa: F811
    tmp, health, _ = env
    nfo = tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E01 - One.nfo"
    nfo.write_text("Some.Show.S01E01.1080p.WEB-GROUP\nSize : 3.99 GiB\nVideo : AVC\n", encoding="utf-8")
    plan = health.check(health.index.build())
    fix = next(x for x in plan["fixes"]["episode-nfos"] if x["path"] == "TV/Some Show/Season 01/Some Show - S01E01 - One.nfo")
    result = health.apply({"fixes": {"episode-nfos": [fix]}}, ["episode-nfos"])
    assert result["failed"] == [] and ET.parse(nfo).getroot().findtext("title") == "One"
    assert any(p.name == nfo.name for p in (tmp / "_q").rglob("*.nfo"))  # the notes are kept in quarantine
    health.journal.undo(result["run"])
    assert nfo.read_text(encoding="utf-8").startswith("Some.Show.S01E01")


def test_a_score_that_cant_be_added_fails_with_its_reason(env):  # noqa: F811
    tmp, health, _ = env
    nfo = tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E02 - Two.nfo"
    nfo.write_text("not an NFO at all", encoding="utf-8")
    fix = {"path": "TV/Some Show/Season 01/Some Show - S01E02 - Two.nfo", "score": [7.2, 200], "label": "Some Show S01E02"}
    result = health.apply({"fixes": {"imdb-scores": [fix]}}, ["imdb-scores"])
    assert result["done"]["imdb-scores"] == 0 and "no place for a score" in result["failed"][0]["why"]


def test_bare_numbers_in_a_season_folder_are_read_and_extras_are_no_questions(env):  # noqa: F811
    tmp, health, _ = env
    show = tmp / "TV" / "Some Show"
    write(show / "Season 02" / "[Group] Some Show - 01 [720p BD 10bit].mkv")  # anime style: no SxxEyy (Magi, Tokyo Ghoul)
    write(show / "Season 01" / "103.mkv")  # Broad City style: 103 = S01E03
    write(show / "Extras" / "Hugh Laurie Interview.mkv")
    write(show / "Season 01" / "[Commie] Some Show - NCOP 1 [BD 720p].mkv")  # an opening without credits
    lib = health.index.build()
    eps = {e["file"]: e for e in next(s for s in lib["shows"] if s["folder"] == "Some Show")["episodes"]}
    assert (eps["Season 02/[Group] Some Show - 01 [720p BD 10bit].mkv"]["season"], eps["Season 02/[Group] Some Show - 01 [720p BD 10bit].mkv"]["episodes"]) == (2, [1])
    assert (eps["Season 01/103.mkv"]["season"], eps["Season 01/103.mkv"]["episodes"]) == (1, [3])
    assert eps["Extras/Hugh Laurie Interview.mkv"]["extra"] and eps["Season 01/[Commie] Some Show - NCOP 1 [BD 720p].mkv"]["extra"]
    asked = [q["path"] for q in health.check(lib)["manual"]["numbers"]]
    assert not any("Interview" in p or "NCOP" in p or "103.mkv" in p for p in asked)
