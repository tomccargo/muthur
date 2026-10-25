"""Episodes numbered without a season ('[Group] Show - 27') are read against TMDB's seasons."""
import os
import time

from muthur.inbox import Inbox, _from_absolute
from muthur.store import Store

TITLES = {1: [f"Episode {n}" for n in range(1, 29)], 2: [f"Second {n}" for n in range(1, 11)]}
TITLES[1][4] = "The Hero"


class FakeTmdb:
    def tv(self, i):
        return {"id": 77, "name": "Frieren", "original_name": "Sousou no Frieren", "original_language": "ja", "first_air_date": "2023-09-29",
                "seasons": [{"season_number": 0, "episode_count": 3}, {"season_number": 1, "episode_count": 28},
                            {"season_number": 2, "episode_count": 10}]}

    def tv_season(self, i, n):
        return {"episodes": [{"episode_number": k, "name": t} for k, t in enumerate(TITLES.get(n, []), 1)]}


def test_from_absolute():
    counts = {0: 3, 1: 28, 2: 10}
    assert _from_absolute(27, None, counts) == (1, 27)
    assert _from_absolute(30, None, counts) == (2, 2)
    assert _from_absolute(3, 2, counts) == (2, 3)  # in a season folder, counted within that season
    assert _from_absolute(31, 1, counts) is None  # the folder says season 1, but 31 lands in season 2
    assert _from_absolute(99, None, counts) is None


def test_absolute_numbers_are_planned_and_checked(tmp_path):
    dl = tmp_path / "complete"
    dl.mkdir()
    for name in ("[Grp] Frieren - 05 - The Hero (1080p).mkv", "[Grp] Frieren - 27 (1080p).mkv", "[Grp] Frieren - 30 (1080p).mkv"):
        (dl / name).write_bytes(b"v")
        t = time.time() - 3600
        os.utime(dl / name, (t, t))
    store = Store(str(tmp_path / "muthur.db"))
    store.remember("tv", "Frieren", 77, 2023, "Frieren", "Frieren (2023)", "library")
    inbox = Inbox(FakeTmdb(), store, str(dl), str(tmp_path / "TV"), str(tmp_path / "Film"))
    items = {i.id: i for i in inbox.scan()}

    hero = items["[Grp] Frieren - 05 - The Hero (1080p).mkv"]
    assert hero.status == "ready"  # the title confirms TMDB's S01E05
    assert hero.files[0].target == "Frieren (2023)/Season 01/Frieren (2023) - S01E05 - The Hero.mkv"

    plain = items["[Grp] Frieren - 27 (1080p).mkv"]
    assert plain.status == "review" and plain.files[0].problem == "absolute"  # no title: checked once in Review
    assert plain.files[0].suggestion == {"season": 1, "episode": 27, "title": None, "part": None}  # 'Episode 27' is no real title
    assert plain.files[0].target.endswith("S01E27.mkv")

    second = items["[Grp] Frieren - 30 (1080p).mkv"]
    assert (second.files[0].season, second.files[0].episodes) == (2, [2])
