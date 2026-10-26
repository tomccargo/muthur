"""A folder matched to the wrong show (26 Oct: 'Shameless' held the US series, matched to the UK one): Health offers
'This is another show', and the old show's episodes in it go to that show's folder or to quarantine."""
from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)

US = ["Pilot Story", "Frank the Plank", "Aunt Ginger", "Casey Casden", "Three Boys", "Killer Carl", "Turtle Time", "Last Knock"]


class TwinTmdb(FakeTmdb):
    """'Twin' twice: the UK one (20, 2008, episodes called 'Episode N') and the US one (21, 2011, real titles)."""

    def tv(self, i):
        if i in (20, 21):
            return {"id": i, "name": "Twin", "first_air_date": "2008-01-01" if i == 20 else "2011-01-01",
                    "seasons": [{"season_number": 1, "episode_count": 8}], "external_ids": {"imdb_id": f"tt{i}0"}}
        return super().tv(i)

    def tv_full(self, i):
        return {**self.tv(i), "poster_path": "/p.jpg", "images": {"logos": []}} if i in (20, 21) else super().tv_full(i)

    def search_tv(self, query, year=None):
        return [{"id": 20, "name": "Twin", "first_air_date": "2008-01-01"}, {"id": 21, "name": "Twin", "first_air_date": "2011-01-01"}] \
            if query.lower() == "twin" else super().search_tv(query, year)

    def tv_season(self, i, n):
        if i == 20:
            return {"episodes": [{"id": 2000 + k, "episode_number": k, "name": f"Episode {k}", "air_date": "2008-02-01"} for k in range(1, 9)]}
        if i == 21:
            return {"episodes": [{"id": 2100 + k, "episode_number": k, "name": t, "air_date": "2011-02-01", "still_path": f"/u{k}.jpg"}
                                 for k, t in enumerate(US, 1)]}
        return super().tv_season(i, n)


def _twin(tmp):
    show, uk = tmp / "TV" / "Twin", tmp / "TV" / "Twin UK"
    write(show / "tvshow.nfo", '<tvshow><title>Twin</title><uniqueid type="tmdb">20</uniqueid></tvshow>')
    write(show / "season01-poster.jpg")  # the UK show's
    for k, t in enumerate(US[:6], 1):
        write(show / "Season 01" / f"Twin S01E{k:02d} - {t} - (2011).mkv")
    write(show / "Season 01" / "Twin S01E07 - Episode 7 - (2008).mp4")  # the UK one's, and Twin UK has it
    write(show / "Season 01" / "Twin S01E07 - Episode 7 - (2008).en.srt")
    write(show / "Season 01" / "Twin S01E08 - Episode 8 - (2008).mp4")  # the UK one's, Twin UK hasn't
    write(uk / "tvshow.nfo", '<tvshow><title>Twin</title><uniqueid type="tmdb">20</uniqueid></tvshow>')
    write(uk / "Season 1" / "Twin S01E07.mkv")


def test_a_folder_of_another_show_is_rematched(env):  # noqa: F811
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = TwinTmdb()
    _twin(tmp)
    plan = health.check(health.index.build())
    fix = next(x for x in plan["fixes"]["show-rematch"])
    assert (fix["path"], fix["from"], fix["to"]) == ("TV/Twin", 20, 21)
    assert sorted(e[2] for e in fix["episodes"]) == [1, 2, 3, 4, 5, 6]
    strays = {s["file"].rsplit("/", 1)[-1]: s["to"] for s in fix["strays"]}
    assert strays["Twin S01E07 - Episode 7 - (2008).mp4"] is None  # Twin UK has it: quarantine
    assert strays["Twin S01E08 - Episode 8 - (2008).mp4"] == "Twin UK/Season 1/Twin S01E08 - Episode 8 - (2008).mp4"
    assert not [q for q in plan["manual"]["numbers"] if q["path"].startswith("TV/Twin/")]  # nothing else asked of it
    assert not plan["fixes"]["show-rematch"][1:]  # Twin UK is the UK show, rightly

    result = health.apply({"fixes": {"show-rematch": [fix]}}, ["show-rematch"])
    assert result["failed"] == []
    show = tmp / "TV" / "Twin"
    assert ">21<" in (show / "tvshow.nfo").read_text(encoding="utf-8")
    assert "Pilot Story" in (show / "Season 01" / "Twin S01E01 - Pilot Story - (2011).nfo").read_text(encoding="utf-8")
    assert (tmp / "TV" / "Twin UK" / "Season 1" / "Twin S01E08 - Episode 8 - (2008).mp4").exists()
    assert not (show / "Season 01" / "Twin S01E07 - Episode 7 - (2008).mp4").exists()
    assert not (show / "Season 01" / "Twin S01E07 - Episode 7 - (2008).en.srt").exists()  # its subtitles went along
    assert not (show / "season01-poster.jpg").exists()
    again = health.check(health.index.build())
    assert not again["fixes"]["show-rematch"]

    health.journal.undo(result["run"])
    assert ">20<" in (show / "tvshow.nfo").read_text(encoding="utf-8")
    assert (show / "Season 01" / "Twin S01E07 - Episode 7 - (2008).mp4").exists()
    assert (show / "Season 01" / "Twin S01E08 - Episode 8 - (2008).mp4").exists()
    assert (show / "season01-poster.jpg").exists()


def test_a_folder_named_after_another_show_is_rematched(env):  # noqa: F811
    """No episode titles (the show's name in every file is no title), but the folder is called nothing like its match."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = TwinTmdb()
    show = tmp / "TV" / "Twin (2011)"
    write(show / "tvshow.nfo", '<tvshow><title>Other Show</title><uniqueid type="tmdb">8</uniqueid></tvshow>')
    for k in range(1, 9):
        write(show / "Season 1" / f"[Grp] Twin - The Series - {k:02d} [720p].mkv")
    plan = health.check(health.index.build())
    fix = next(x for x in plan["fixes"]["show-rematch"] if x["path"] == "TV/Twin (2011)")
    assert (fix["from"], fix["to"]) == (8, 21) and len(fix["episodes"]) == 8


def test_a_show_in_another_order_is_not_rematched(env):  # noqa: F811
    """Titles of the matched show at other numbers: its own episodes, numbered differently."""
    tmp, health, _ = env
    health.tmdb = health.scores.tmdb = TwinTmdb()
    show = tmp / "TV" / "Twin"
    write(show / "tvshow.nfo", '<tvshow><title>Twin</title><uniqueid type="tmdb">21</uniqueid></tvshow>')
    for k, t in enumerate(reversed(US), 1):
        write(show / "Season 01" / f"Twin S01E{k:02d} - {t}.mkv")
    plan = health.check(health.index.build())
    assert not plan["fixes"]["show-rematch"]
