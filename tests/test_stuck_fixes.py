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


def test_a_score_that_cant_be_added_fails_with_its_reason(env):  # noqa: F811
    tmp, health, _ = env
    nfo = tmp / "TV" / "Some Show" / "Season 01" / "Some Show - S01E02 - Two.nfo"
    nfo.write_text("not an NFO at all", encoding="utf-8")
    fix = {"path": "TV/Some Show/Season 01/Some Show - S01E02 - Two.nfo", "score": [7.2, 200], "label": "Some Show S01E02"}
    result = health.apply({"fixes": {"imdb-scores": [fix]}}, ["imdb-scores"])
    assert result["done"]["imdb-scores"] == 0 and "no place for a score" in result["failed"][0]["why"]
