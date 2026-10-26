"""Renaming an episode: what belongs to it moves along, nothing is overwritten, and Kodi keeps its watched status."""
import pytest
from test_health import env  # noqa: F401  (the Health fixture)

from muthur.journal import Journal
from muthur.rename import follow_in_kodi, moves, new_name, rename
from muthur.store import Store


def write(p, data="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


@pytest.fixture
def tv(tmp_path):
    s1 = tmp_path / "TV" / "The Office (US)" / "Season 2"
    for n in ("The.Office.S02E01.720p.mkv", "The.Office.S02E01.720p.nfo", "The.Office.S02E01.720p-thumb.jpg",
              "The.Office.S02E01.720p.en.srt", "The.Office.S02E01.720p.Part.Two.en.srt", "The.Office.S02E02.mkv"):
        write(s1 / n)
    return tmp_path


def test_the_new_name_and_what_moves_with_it(tv):
    name = new_name("The Office (US)", "Season 2/The.Office.S02E01.720p.mkv", 2, [1], "The Dundies")
    assert name == "The Office (US) - S02E01 - The Dundies.mkv"
    got = moves(str(tv / "TV"), "The Office (US)/Season 2/The.Office.S02E01.720p.mkv", name)
    to = [b.rsplit("/", 1)[1] for _, b in got]
    assert to == ["The Office (US) - S02E01 - The Dundies.mkv", "The Office (US) - S02E01 - The Dundies-thumb.jpg",
                  "The Office (US) - S02E01 - The Dundies.en.srt", "The Office (US) - S02E01 - The Dundies.nfo"]  # not another video's subtitle


def test_a_rename_is_journalled_never_overwrites_and_can_be_put_back(tv):
    store = Store(str(tv / "muthur.db"))
    journal = Journal(store)
    root, s2 = str(tv / "TV"), tv / "TV" / "The Office (US)" / "Season 2"
    before = sorted(p.name for p in s2.iterdir())
    run = journal.start("library")
    new = rename(journal, run, root, "TV", "The Office (US)/Season 2/The.Office.S02E01.720p.mkv", "The Office (US) - S02E01 - The Dundies.mkv")
    assert new == "TV/The Office (US)/Season 2/The Office (US) - S02E01 - The Dundies.mkv" and (s2 / "The Office (US) - S02E01 - The Dundies.nfo").exists()
    with pytest.raises(ValueError, match="already exists"):  # S02E02's new name is taken: nothing moves
        rename(journal, run, root, "TV", "The Office (US)/Season 2/The.Office.S02E02.mkv", "The Office (US) - S02E01 - The Dundies.mkv")
    assert (s2 / "The.Office.S02E02.mkv").exists()
    journal.undo(run)
    assert sorted(p.name for p in s2.iterdir()) == before


class FakeKodi:
    """Kodi with the old entry (watched twice, id 7); after the scan, the new file is entry 8."""

    def __init__(self):
        self.calls, self.scans = [], []

    def source_prefix(self, name):
        return "smb://nas/TV/" if name == "TV" else None

    def scan_and_wait(self, folder):
        self.scans.append(folder)
        return True

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "VideoLibrary.GetEpisodes":
            return {"episodes": [{"episodeid": 8, "file": "smb://nas/TV/Show/Season 1/Show - S01E01 - Pilot.mkv", "playcount": 0, "resume": {}}]}
        return "OK"


def test_kodi_scans_once_carries_the_play_count_and_drops_the_old_entry():
    k = FakeKodi()
    before = {"tv/show/season 1/show.s01e01.mkv": {"kodiid": 7, "playcount": 2, "lastplayed": "2024-01-01 20:00:00", "resume": 0, "total": 0}}
    r = follow_in_kodi(k, [("TV/Show/Season 1/Show.S01E01.mkv", "TV/Show/Season 1/Show - S01E01 - Pilot.mkv")], {"TV": "/data/TV"}, before)
    assert r == {"followed": 1, "problems": []} and k.scans == ["smb://nas/TV/Show/Season 1/"]
    assert ("VideoLibrary.SetEpisodeDetails", {"episodeid": 8, "playcount": 2, "lastplayed": "2024-01-01 20:00:00"}) in k.calls
    assert ("VideoLibrary.RemoveEpisode", {"episodeid": 7}) in k.calls


def test_health_renames_only_while_kodi_answers(env):  # noqa: F811
    tmp, health, plan = env
    fix = next(x for x in plan["fixes"]["renames"] if x["path"].startswith("TV/Other Show"))
    assert fix["to"] == "Other Show (2019) - S01E01 - One.mkv"  # the show folder's name, TMDB's title
    assert all("Some Show - S01E03" not in x["path"] for x in plan["fixes"]["renames"])  # its number is a question: not renamed

    class Off:
        def check(self):
            return {"connected": False}

    off = health.apply({"fixes": {"renames": [fix]}}, ["renames"], Off())
    assert off["done"]["renames"] == 0 and "Kodi is off" in off["failed"][0]["why"]

    class On(FakeKodi):
        def check(self):
            return {"connected": True}

        def call(self, method, params=None):
            if method == "VideoLibrary.GetEpisodes" and params.get("properties") == ["file", "playcount", "resume"]:
                return {"episodes": [{"episodeid": 8, "file": "smb://nas/TV/Other Show (2019)/Season 01/Other Show (2019) - S01E01 - One.mkv",
                                      "playcount": 0, "resume": {}}]}
            return super().call(method, params) if method != "VideoLibrary.GetEpisodes" else {"episodes": []}

    import muthur.rename as rename_mod

    before = {"tv/other show (2019)/season 01/other show - s01e01 - one.mkv": {"kodiid": 7, "playcount": 1, "lastplayed": None, "resume": 0, "total": 0}}
    rename_mod.read_before, saved = (lambda kodi, roots: before), rename_mod.read_before
    try:
        on = health.apply({"fixes": {"renames": [fix]}}, ["renames"], On())
    finally:
        rename_mod.read_before = saved
    assert on["failed"] == [] and on["done"]["renames"] == 1 and on["kodiRenames"] == {"followed": 1, "problems": []}
    assert (tmp / "TV" / "Other Show (2019)" / "Season 01" / "Other Show (2019) - S01E01 - One.mkv").exists()
