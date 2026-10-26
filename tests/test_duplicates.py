"""Duplicates: ranking, the plan (names, sidecars, folders), applying it, undo, and carrying watched status."""
import os

import pytest

from muthur import duplicates
from muthur.duplicates import Duplicates, apply_groups
from muthur.index import Index
from muthur.journal import Journal
from muthur.store import Store

FACTS = {  # what ffprobe would say, by a word in the file name
    "480p": {"width": 720, "height": 404, "vcodec": "h264", "acodec": "aac", "aprofile": None, "channels": 2, "duration": 2600, "subtitles": 0},
    "1080p": {"width": 1920, "height": 1080, "vcodec": "h264", "acodec": "ac3", "aprofile": None, "channels": 6, "duration": 2600, "subtitles": 0},
    "2160p": {"width": 3840, "height": 2160, "vcodec": "hevc", "acodec": "eac3", "aprofile": None, "channels": 6, "duration": 9000, "subtitles": 0},
}


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch):
    monkeypatch.setattr(duplicates, "probe", lambda path: next((v for k, v in FACTS.items() if k in os.path.basename(path)), None))


def write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def lib(tmp_path):
    tv, film = tmp_path / "TV", tmp_path / "Film"
    show = tv / "Some Show"
    (show / "tvshow.nfo").parent.mkdir(parents=True)
    (show / "tvshow.nfo").write_text('<tvshow><title>Some Show</title><uniqueid type="tmdb">7</uniqueid></tvshow>')
    a = show / "Season 01" / "Some Show S01E01 - Pilot - 480p"
    write(a.with_suffix(".mp4"), b"small" * 10)
    write(a.parent / (a.name + ".nfo"), b"<episodedetails><title>Pilot</title></episodedetails>")
    write(a.parent / (a.name + "-thumb.jpg"))
    write(a.parent / (a.name + ".en.srt"))
    write(show / "Season 01" / "Some.Show.S01E01.1080p.BluRay.x264-GRP.mkv", b"big" * 100)
    write(show / "Season 01" / "Some Show S01E02 - Two - 1080p.mkv", b"only one")  # not a duplicate
    write(film / "Dune (2021)" / "Dune.2021.1080p.WEBRip.mp4", b"web" * 50)
    write(film / "Dune (2021)" / "Dune.2021.1080p.WEBRip.nfo", b'<movie><title>Dune</title><uniqueid type="imdb">tt1160419</uniqueid></movie>')
    write(film / "Dune (2021)" / "poster.jpg")
    write(film / "Dune.2021.2160p.WEB-DL" / "Dune.2021.2160p.WEB-DL.mkv", b"uhd" * 200)
    write(film / "Dune.2021.2160p.WEB-DL" / "Dune.2021.2160p.WEB-DL.nfo", b'<movie><title>Dune</title><uniqueid type="imdb">tt1160419</uniqueid></movie>')
    store = Store(str(tmp_path / "muthur.db"))
    index = Index(store, str(tv), str(film)).build()
    dups = Duplicates(store, str(tv), str(film))
    return tmp_path, store, dups, dups.find(index)


def test_groups_and_plans(lib):
    _, _, _, groups = lib
    assert sorted(g["label"] for g in groups) == ["Dune", "Some Show S01E01"]
    ep = next(g for g in groups if g["kind"] == "episode")
    assert ep["keep"] == "TV/Some Show/Season 01/Some.Show.S01E01.1080p.BluRay.x264-GRP.mkv"
    # The kept video takes the library name (the copy with the NFO), with its own resolution.
    final = "TV/Some Show/Season 01/Some Show S01E01 - Pilot - 1080p"
    assert ep["plan"]["final"] == final + ".mkv"
    ops = [(o["op"], o["src"].rsplit("/", 1)[1], o.get("dst", "").rsplit("/", 1)[-1]) for o in ep["plan"]["ops"]]
    assert ops == [
        ("quarantine", "Some Show S01E01 - Pilot - 480p.mp4", ""),
        ("move", "Some Show S01E01 - Pilot - 480p-thumb.jpg", "Some Show S01E01 - Pilot - 1080p-thumb.jpg"),
        ("move", "Some Show S01E01 - Pilot - 480p.en.srt", "Some Show S01E01 - Pilot - 1080p.en.srt"),
        ("move", "Some Show S01E01 - Pilot - 480p.nfo", "Some Show S01E01 - Pilot - 1080p.nfo"),
        ("move", "Some.Show.S01E01.1080p.BluRay.x264-GRP.mkv", "Some Show S01E01 - Pilot - 1080p.mkv"),
    ]
    film = next(g for g in groups if g["kind"] == "film")
    assert film["keep"].endswith("2160p.WEB-DL.mkv")
    assert film["plan"]["final"] == "Film/Dune (2021)/Dune (2021).mkv"  # into the curated folder, under its name
    assert film["plan"]["ops"][-1] == {"op": "quarantine", "src": "Film/Dune.2021.2160p.WEB-DL"}


def test_apply_and_undo(lib):
    tmp, store, dups, groups = lib
    journal = Journal(store)
    before = sorted(str(p.relative_to(tmp)) for p in (tmp / "TV").rglob("*")) + sorted(str(p.relative_to(tmp)) for p in (tmp / "Film").rglob("*"))
    result = apply_groups(dups, groups, journal, str(tmp / "_q"))
    assert result["applied"] == 2, result
    season = tmp / "TV" / "Some Show" / "Season 01"
    assert (season / "Some Show S01E01 - Pilot - 1080p.mkv").read_bytes() == b"big" * 100
    assert (season / "Some Show S01E01 - Pilot - 1080p.nfo").exists() and (season / "Some Show S01E01 - Pilot - 1080p.en.srt").exists()
    assert not (season / "Some Show S01E01 - Pilot - 480p.mp4").exists()
    assert (tmp / "Film" / "Dune (2021)" / "Dune (2021).mkv").read_bytes() == b"uhd" * 200
    assert (tmp / "Film" / "Dune (2021)" / "Dune (2021).nfo").exists() and (tmp / "Film" / "Dune (2021)" / "poster.jpg").exists()
    assert not (tmp / "Film" / "Dune.2021.2160p.WEB-DL").exists()
    assert any((tmp / "_q").rglob("Dune.2021.1080p.WEBRip.mp4"))
    journal.undo(result["run"])
    after = sorted(str(p.relative_to(tmp)) for p in (tmp / "TV").rglob("*")) + sorted(str(p.relative_to(tmp)) for p in (tmp / "Film").rglob("*"))
    assert after == before


def test_a_changed_copy_stops_its_group(lib):
    tmp, store, dups, groups = lib
    (tmp / "TV" / "Some Show" / "Season 01" / "Some Show S01E01 - Pilot - 480p.mp4").write_bytes(b"changed")
    result = apply_groups(dups, groups, Journal(store), str(tmp / "_q"))
    stopped = [r for r in result["items"] if not r["ok"]]
    assert len(stopped) == 1 and "changed since muthur measured it" in stopped[0]["why"]


class FakeKodi:
    """Kodi with the two copies of S01E01 in its library; the 480p one was watched twice."""

    def __init__(self, root):
        self.root, self.prefix = root, "smb://nas/share/"
        base = self.prefix + "TV/Some Show/Season 01/"
        self.eps = [{"episodeid": 1, "tvshowid": 1, "season": 1, "episode": 1, "playcount": 2, "lastplayed": "2026-01-01 20:00:00",
                     "resume": {"position": 0, "total": 0}, "file": base + "Some Show S01E01 - Pilot - 480p.mp4", "showtitle": "Some Show"},
                    {"episodeid": 2, "tvshowid": 1, "season": 1, "episode": 1, "playcount": 0, "lastplayed": "",
                     "resume": {"position": 0, "total": 0}, "file": base + "Some.Show.S01E01.1080p.BluRay.x264-GRP.mkv", "showtitle": "Some Show"}]
        self.calls = []

    def source_prefix(self, name):
        return self.prefix + name + "/"

    def scan_and_wait(self, directory=None, limit=300, waited=None):
        folder = self.root / directory[len(self.prefix):]
        for f in folder.iterdir():
            path = directory + f.name
            if f.suffix in (".mkv", ".mp4") and not any(e["file"] == path for e in self.eps):
                self.eps.append({"episodeid": 10 + len(self.eps), "tvshowid": 1, "season": 1, "episode": 1, "playcount": 0,
                                 "lastplayed": "", "resume": {"position": 0, "total": 0}, "file": path, "showtitle": "Some Show"})
        return True

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "VideoLibrary.GetTVShows":
            return {"tvshows": [{"tvshowid": 1, "title": "Some Show", "uniqueid": {"tmdb": "7"}}]}
        if method == "VideoLibrary.GetEpisodes":
            if params and "filter" in params:
                return {"episodes": [e for e in self.eps if e["file"].rsplit("/", 1)[1] == params["filter"]["value"]]}
            return {"episodes": self.eps}
        if method == "VideoLibrary.GetMovies":
            return {"movies": []}
        return "OK"


def test_watched_status_goes_to_the_kept_copy(lib):
    tmp, store, dups, groups = lib
    kodi = FakeKodi(tmp)
    ep = [g for g in groups if g["kind"] == "episode"]
    result = apply_groups(dups, ep, Journal(store), str(tmp / "_q"), kodi)
    assert result["items"][0]["kodi"] == {"ok": True, "playcount": 2, "removed": 2}
    sets = [p for m, p in kodi.calls if m == "VideoLibrary.SetEpisodeDetails"]
    assert sets == [{"episodeid": 12, "playcount": 2, "lastplayed": "2026-01-01 20:00:00"}]
    assert sorted(p["episodeid"] for m, p in kodi.calls if m == "VideoLibrary.RemoveEpisode") == [1, 2]


def test_hdr_only_counts_when_wanted():
    sdr = {**FACTS["2160p"], "hdr": False}
    hdr = {**FACTS["2160p"], "hdr": True}
    a = duplicates.quality("Film.2160p.WEB-DL.mkv", 1, sdr, 0)
    b = duplicates.quality("Film.2160p.WEB-DL.HDR.mkv", 1, hdr, 0)
    assert a["rank"] == b["rank"]  # by default HDR is no reason to win
    assert duplicates.quality("Film.2160p.WEB-DL.HDR.mkv", 1, hdr, 0, prefer_hdr=True)["rank"] > a["rank"]
    assert "HDR" in duplicates.describe(b)
