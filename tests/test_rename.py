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
    got = moves(str(tv / "TV"), "The Office (US)/Season 2/The.Office.S02E01.720p.mkv", f"The Office (US)/Season 2/{name}")
    to = [b.rsplit("/", 1)[1] for _, b in got]
    assert to == ["The Office (US) - S02E01 - The Dundies.mkv", "The Office (US) - S02E01 - The Dundies-thumb.jpg",
                  "The Office (US) - S02E01 - The Dundies.en.srt", "The Office (US) - S02E01 - The Dundies.nfo"]  # not another video's subtitle


def test_a_rename_is_journalled_never_overwrites_and_can_be_put_back(tv):
    store = Store(str(tv / "muthur.db"))
    journal = Journal(store)
    root, s2 = str(tv / "TV"), tv / "TV" / "The Office (US)" / "Season 2"
    before = sorted(p.name for p in s2.iterdir())
    run = journal.start("library")
    new = rename(journal, run, root, "TV", "The Office (US)/Season 2/The.Office.S02E01.720p.mkv", "The Office (US)/Season 2/The Office (US) - S02E01 - The Dundies.mkv")
    assert new == "TV/The Office (US)/Season 2/The Office (US) - S02E01 - The Dundies.mkv" and (s2 / "The Office (US) - S02E01 - The Dundies.nfo").exists()
    with pytest.raises(ValueError, match="already exists"):  # S02E02's new name is taken: nothing moves
        rename(journal, run, root, "TV", "The Office (US)/Season 2/The.Office.S02E02.mkv", "The Office (US)/Season 2/The Office (US) - S02E01 - The Dundies.mkv")
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
    seen: list[str] = []
    follow_in_kodi(k, [("TV/Show/Season 1/Show.S01E01.mkv", "TV/Show/Season 1/Show - S01E01 - Pilot.mkv")], {"TV": "/data/TV"}, before, done=seen.append)
    assert seen == ["TV/Show/Season 1/Show.S01E01.mkv"]  # each one Kodi took is crossed off the waiting list
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
    rename_mod.read_before, saved = (lambda kodi, roots, backup=None: before), rename_mod.read_before
    try:
        on = health.apply({"fixes": {"renames": [fix]}}, ["renames"], On())
    finally:
        rename_mod.read_before = saved
    assert on["failed"] == [] and on["done"]["renames"] == 1 and on["kodiRenames"] == {"followed": 1, "problems": []}
    assert (tmp / "TV" / "Other Show (2019)" / "Season 01" / "Other Show (2019) - S01E01 - One.mkv").exists()


def test_films_get_title_and_year_and_a_folder_of_their_own(env, monkeypatch):  # noqa: F811
    tmp, health, _ = env
    film = tmp / "Film"
    site = film / "www.Site.com   -   Some.Film.2005.1080p"
    write(site / "Some.Film.2005.1080p.mkv")
    write(site / "Some.Film.2005.1080p.nfo", "<movie><title>Some Film</title><year>2005</year></movie>")
    write(site / "Some.Film.2005.1080p.en.srt")
    write(site / "poster.jpg")
    write(site / "Torrent Downloaded From www.Site.com.txt")
    write(film / "Loose.Film.1999.mkv")
    write(film / "Loose.Film.1999.nfo", "<movie><title>Loose Film</title><year>1999</year></movie>")
    write(film / "Loose.Film.1999-poster.jpg")
    plan = health.check(health.index.build())
    fixes = {x["label"]: x for x in plan["fixes"]["film-renames"]}
    assert fixes["Some Film (2005)"]["to"] == "Some Film (2005)/Some Film (2005).mkv"
    assert fixes["Loose Film (1999)"]["to"] == "Loose Film (1999)/Loose Film (1999).mkv"

    class On:
        def check(self):
            return {"connected": True}

    monkeypatch.setattr("muthur.rename.read_before", lambda kodi, roots, backup=None: {})
    monkeypatch.setattr("muthur.rename.follow_in_kodi", lambda kodi, renamed, roots, before, done=None: {"followed": len(renamed), "problems": []})
    before = sorted(str(p.relative_to(film)) for p in film.rglob("*") if p.is_file())
    result = health.apply(plan, ["film-renames"], On())
    assert result["failed"] == [] and result["done"]["film-renames"] == 2
    now = sorted(str(p.relative_to(film)).replace("\\", "/") for p in film.rglob("*") if p.is_file() and "Film (" in str(p))
    assert now == ["Loose Film (1999)/Loose Film (1999)-poster.jpg", "Loose Film (1999)/Loose Film (1999).mkv", "Loose Film (1999)/Loose Film (1999).nfo",
                   "Some Film (2005)/Some Film (2005).en.srt", "Some Film (2005)/Some Film (2005).mkv", "Some Film (2005)/Some Film (2005).nfo",
                   "Some Film (2005)/poster.jpg"]  # the site's note went to quarantine
    # What a restart in the Kodi step would leave to finish: read back from the journal, folder moves included.
    from muthur.rename import from_run

    assert sorted(from_run(health.journal.ops(result["run"]), health.roots)) == [
        ("Film/Loose.Film.1999.mkv", "Film/Loose Film (1999)/Loose Film (1999).mkv"),
        ("Film/www.Site.com   -   Some.Film.2005.1080p/Some.Film.2005.1080p.mkv", "Film/Some Film (2005)/Some Film (2005).mkv")]
    health.journal.undo(result["run"])
    assert sorted(str(p.relative_to(film)) for p in film.rglob("*") if p.is_file()) == before


def test_a_run_a_restart_cut_short_is_closed_and_its_renames_wait_for_kodi(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from muthur.web import Config, create_app

    for k, v in {"MUTHUR_CONFIG": tmp_path / "config", "MUTHUR_DOWNLOADS": tmp_path / "dl", "MUTHUR_TV": tmp_path / "TV",
                 "MUTHUR_FILM": tmp_path / "Film", "MUTHUR_QUARANTINE": tmp_path / "_q"}.items():
        monkeypatch.setenv(k, str(v))
    app = create_app(Config(dotenv=False))
    journal, store = Journal(app.state.store), app.state.store
    old, new = tmp_path / "Film" / "Old.Name.mkv", tmp_path / "Film" / "New (2001)" / "New (2001).mkv"
    write(old)
    run = journal.start("health")  # the files moved, then muthur was restarted before Kodi was told
    journal.move(run, "Film/Old.Name.mkv", str(old), str(new), "move")
    assert TestClient(app).get("/api/health").json() == {"ok": True, "busy": False}

    create_app(Config(dotenv=False))  # the restart
    assert journal.unfinished() == []
    assert journal.runs(1)[0]["summary"]["interrupted"] is True
    assert store.get("kodi.pendingRenames") == [["Film/Old.Name.mkv", "Film/New (2001)/New (2001).mkv"]]
