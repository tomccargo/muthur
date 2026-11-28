"""Automatic pick-up (autopick.py, web.py auto_look) and archives (archives.py): finished downloads are filed without
the reader, fake archives go to quarantine, real ones are unpacked, and nothing is done twice or while muthur is busy."""
import os
import subprocess
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_web import FakeTmdb

from muthur import archives, autopick
from muthur.web import Config, create_app

OLD = time.time() - 3600


def _old(*paths):
    for p in paths:
        os.utime(p, (OLD, OLD))


def _zip(path, members: dict, encrypted: set = frozenset()):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), data)
    if encrypted:  # zipfile can't write a locked member: set the 'encrypted' flag in both headers, as a locked zip has
        raw = bytearray(path.read_bytes())
        for sig, at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            i = raw.find(sig)
            while i != -1:
                raw[i + at] |= 0x1
                i = raw.find(sig, i + 4)
        path.write_bytes(bytes(raw))
    _old(path)


# -- archives: what is inside -------------------------------------------------------
def test_a_zip_with_a_video_is_media(tmp_path):
    _zip(tmp_path / "Some.Film.1999.1080p.zip", {"Some.Film.1999.1080p.mkv": b"v" * 100, "info.nfo": b"n"})
    found = archives.look(str(tmp_path), "Some.Film.1999.1080p.zip")
    assert found.verdict == "media" and found.size == 101


@pytest.mark.parametrize("members, encrypted, why", [
    ({"Some.Show.S01E09.1080p.mkv.exe": b"MZ", "readme.txt": b"r"}, set(), "program"),
    ({"Some.Show.S01E09.1080p.mkv": b"v"}, {"Some.Show.S01E09.1080p.mkv"}, "password"),
    ({"../../TV/evil.mkv": b"v"}, set(), "outside"),
    ({"Password.txt": b"go to a site", "cover.jpg": b"j"}, set(), "no video"),
    ({"Sample/some.show.s01e09.sample.mkv": b"s"}, set(), "sample"),
])
def test_a_fake_zip_is_told_apart(tmp_path, members, encrypted, why):
    _zip(tmp_path / "Some.Show.S01E09.1080p.WEB.zip", members, encrypted)
    found = archives.look(str(tmp_path), "Some.Show.S01E09.1080p.WEB.zip")
    assert found.verdict == "fake" and why in found.why


def test_a_split_set_or_a_nested_archive_is_left_to_the_reader(tmp_path):
    d = tmp_path / "Some.Show.S01E09.1080p.WEB-GRP"
    d.mkdir()
    for n in ("grp.part01.rar", "grp.part02.rar"):
        (d / n).write_bytes(b"Rar!")
    assert archives.look(str(tmp_path), d.name).verdict == "unknown"
    (tmp_path / "x.zip").unlink(missing_ok=True)
    _zip(tmp_path / "Some.Show.S01E10.zip", {"inner.rar": b"Rar!"})
    found = archives.look(str(tmp_path), "Some.Show.S01E10.zip")
    assert found.verdict == "unknown" and "inside an archive" in found.why


def test_a_rar_is_read_with_bsdtar_and_a_password_is_a_fake(tmp_path):
    (tmp_path / "Some.Show.S01E09.rar").write_bytes(b"Rar!")
    listing = ("-rw-r--r--  0 0      0   734003200 Jan  1  2026 Some.Show.S01E09.1080p.mkv\n"
               "-rw-r--r--  0 0      0          12 Jan  1  2026 Some Show info.nfo\n")

    def run(args, **kw):
        assert args[:2] == ["bsdtar", "-tvf"]
        return subprocess.CompletedProcess(args, 0, listing, "")
    found = archives.look(str(tmp_path), "Some.Show.S01E09.rar", run)
    assert found.verdict == "media" and found.size == 734003212

    def locked(args, **kw):
        return subprocess.CompletedProcess(args, 1, "", "bsdtar: Encrypted file is unsupported")
    assert archives.look(str(tmp_path), "Some.Show.S01E09.rar", locked).verdict == "fake"

    def program(args, **kw):
        return subprocess.CompletedProcess(args, 0, "-rwxr-xr-x  0 0 0 1000 Jan  1  2026 Some.Show.S01E09.exe\n", "")
    assert archives.look(str(tmp_path), "Some.Show.S01E09.rar", program).verdict == "fake"


def test_unpacking_lands_in_the_downloads_folder_with_the_archives_time(tmp_path):
    d = tmp_path / "Some.Film.1999.1080p.BluRay-GRP"
    (d / "Sample").mkdir(parents=True)
    (d / "Sample" / "grp-sample.mkv").write_bytes(b"s")
    (d / "Some.Film.1999.en.srt").write_text("1")
    _zip(d / "grp.zip", {"Some.Film.1999.1080p.BluRay-GRP.mkv": b"v" * 10})
    found = archives.look(str(tmp_path), d.name)
    done = archives.unpack(str(tmp_path), d.name, found)
    video = d / "Some.Film.1999.1080p.BluRay-GRP.mkv"
    assert done == {"folder": d.name, "files": 1, "archives": [f"{d.name}/grp.zip"]}
    assert video.read_bytes() == b"v" * 10 and abs(video.stat().st_mtime - OLD) < 2
    assert (d / "Some.Film.1999.en.srt").exists()  # what came beside the archive stays
    assert not (tmp_path / archives.STAGING).exists()

    _zip(tmp_path / "Some.Show.S01E09.zip", {"Some.Show.S01E09.mkv": b"e"})
    loose = archives.unpack(str(tmp_path), "Some.Show.S01E09.zip", archives.look(str(tmp_path), "Some.Show.S01E09.zip"))
    assert loose["folder"] == "Some.Show.S01E09" and (tmp_path / "Some.Show.S01E09" / "Some.Show.S01E09.mkv").exists()


def test_unpacking_never_overwrites(tmp_path):
    d = tmp_path / "Some.Film.1999"
    d.mkdir()
    (d / "Some.Film.1999.mkv").write_bytes(b"mine")
    _zip(d / "a.zip", {"Some.Film.1999.mkv": b"theirs"})
    with pytest.raises(ValueError):
        archives.unpack(str(tmp_path), d.name, archives.Look("media", "", ["a.zip"]))
    assert (d / "Some.Film.1999.mkv").read_bytes() == b"mine"


# -- the watcher's rules -----------------------------------------------------------------
def test_a_download_is_settled_when_download_station_or_the_clock_says_so(tmp_path):
    now = time.time()
    assert autopick.settled([1, 10, now - 700], None, now)
    assert not autopick.settled([1, 10, now - 30], None, now)  # still being written
    assert autopick.settled([1, 10, now - 30], {"status": "seeding"}, now)
    assert not autopick.settled([1, 10, now - 7000], {"status": "downloading"}, now)
    assert not autopick.settled([0, 0, 0], None, now)


def test_the_look_key_changes_only_when_something_settles(tmp_path):
    (tmp_path / "a.mkv").write_bytes(b"a")
    _old(tmp_path / "a.mkv")
    (tmp_path / "b.mkv").write_bytes(b"b")  # fresh: not settled
    now = time.time()
    key = autopick.look_key(str(tmp_path), ["a.mkv", "b.mkv"], None, now)
    (tmp_path / "b.mkv").write_bytes(b"bb")  # still downloading: nothing to do
    assert autopick.look_key(str(tmp_path), ["a.mkv", "b.mkv"], None, now) == key
    assert autopick.look_key(str(tmp_path), ["a.mkv", "b.mkv"], {"b.mkv": {"status": "finished"}}, now) != key


# -- the whole pick-up through the app ----------------------------------------------------
@pytest.fixture
def app(tmp_path, monkeypatch):
    dl = tmp_path / "torrent-output"
    show = dl / "Some.Show.S01E02.1080p.WEB.h264-GRP"
    show.mkdir(parents=True)
    (show / "some.show.s01e02.1080p.web.h264-grp.mkv").write_bytes(b"x" * 10)
    (show / "Downloaded from site.txt").write_text("hi")
    _old(*show.iterdir())
    _zip(dl / "Some.Film.1999.1080p.BluRay.x264-GRP.zip", {"Some.Film.1999.1080p.BluRay.x264-GRP.mkv": b"y" * 10})
    _zip(dl / "Some.Show.S01E09.1080p.WEB.h264-GRP.zip", {"Some.Show.S01E09.1080p.WEB.h264-GRP.mkv.exe": b"MZ"})
    (dl / "Unknown.Thing.S01E01.mkv").write_bytes(b"u")  # nothing on TMDB: Review
    _old(dl / "Unknown.Thing.S01E01.mkv")
    (dl / "Some.Show.S01E03.mkv").write_bytes(b"still coming")  # written a moment ago
    for k, v in {"MUTHUR_CONFIG": tmp_path / "config", "MUTHUR_DOWNLOADS": dl, "MUTHUR_TV": tmp_path / "TV",
                 "MUTHUR_FILM": tmp_path / "Film", "MUTHUR_WEB": tmp_path / "no-web"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("TMDB_READ_TOKEN", raising=False)
    (tmp_path / "TV").mkdir()
    (tmp_path / "Film").mkdir()
    a = create_app(Config(dotenv=False), tmdb_factory=FakeTmdb)
    c = TestClient(a)
    c.put("/api/settings", json={"tmdb": {"token": "fake"}})
    return c


def _wait(c):
    for _ in range(200):
        job = c.get("/api/jobs/current").json()
        if job and not job["running"] and not c.get("/api/status").json()["queue"]:
            return job
        time.sleep(0.05)
    raise AssertionError("the pick-up didn't finish")


def test_finished_downloads_are_filed_unpacked_or_quarantined_without_the_reader(app, tmp_path):
    assert app.app.state.auto_look() is True
    job = _wait(app)
    assert job["name"] == "auto" and job["error"] is None and job["by_user"] is False
    dl = tmp_path / "torrent-output"

    # A plain download and an unpacked zip are in the library; the zip itself is in quarantine.
    assert (tmp_path / "TV" / "Some Show (2021)" / "Season 01" / "Some Show (2021) - S01E02 - The Second One.mkv").exists()
    assert (tmp_path / "Film" / "Een Film (1999)" / "Een Film (1999).mkv").read_bytes() == b"y" * 10
    assert not (dl / "Some.Film.1999.1080p.BluRay.x264-GRP.zip").exists()
    day = tmp_path / "_muthur-quarantine" / time.strftime("%Y-%m-%d")
    assert list(day.rglob("Some.Film.1999.1080p.BluRay.x264-GRP.zip"))
    # The fake zip went to quarantine; the one still being written and the one that needs a choice stay.
    assert not (dl / "Some.Show.S01E09.1080p.WEB.h264-GRP.zip").exists() and list(day.rglob("Some.Show.S01E09*.zip"))
    assert (dl / "Some.Show.S01E03.mkv").exists() and (dl / "Unknown.Thing.S01E01.mkv").exists()

    log = {(r["what"], r["id"]) for r in app.get("/api/auto").json()["log"]}
    assert ("filed", "Some.Show.S01E02.1080p.WEB.h264-GRP") in log
    assert ("unpacked", "Some.Film.1999.1080p.BluRay.x264-GRP") in log
    assert ("filed", "Some.Film.1999.1080p.BluRay.x264-GRP") in log
    assert ("quarantined", "Some.Show.S01E09.1080p.WEB.h264-GRP.zip") in log
    assert ("review", "Unknown.Thing.S01E01.mkv") in log
    runs = app.get("/api/history").json()["runs"]
    assert any(r["kind"] == "apply" and r["summary"].get("auto") for r in runs)

    # Nothing new settled: the next look starts nothing, and Review isn't logged twice.
    before = len(app.get("/api/auto").json()["log"])
    assert app.app.state.auto_look() is False
    _old(dl / "Some.Show.S01E03.mkv")  # now it has settled: a new pick-up files it
    assert app.app.state.auto_look() is True
    _wait(app)
    rows = app.get("/api/auto").json()["log"]
    assert [r["what"] for r in rows[: len(rows) - before]] == ["filed"]


def test_a_download_that_couldnt_be_filed_isnt_tried_again(app, tmp_path):
    taken = tmp_path / "TV" / "Some Show (2021)" / "Season 01"
    taken.mkdir(parents=True)
    (taken / "Some Show (2021) - S01E02 - Another copy.mkv").write_bytes(b"old")  # already in the library: Review
    app.app.state.auto_look()
    _wait(app)
    assert (tmp_path / "torrent-output" / "Some.Show.S01E02.1080p.WEB.h264-GRP").exists()
    first = [r for r in app.get("/api/auto").json()["log"] if r["id"] == "Some.Show.S01E02.1080p.WEB.h264-GRP"]
    assert [r["what"] for r in first] == ["review"]
    _old(tmp_path / "torrent-output" / "Some.Show.S01E03.mkv")
    app.app.state.auto_look()
    _wait(app)
    again = [r for r in app.get("/api/auto").json()["log"] if r["id"] == "Some.Show.S01E02.1080p.WEB.h264-GRP"]
    assert len(again) == 1


def test_no_pick_up_when_switched_off_and_only_plans_in_a_dry_run(app, tmp_path):
    app.put("/api/settings", json={"autoPickup": False})
    assert app.get("/api/settings").json()["autoPickup"] is False
    assert app.app.state.auto_look() is False

    app.put("/api/settings", json={"autoPickup": True, "dryRun": True})
    assert app.app.state.auto_look() is True
    _wait(app)
    assert (tmp_path / "torrent-output" / "Some.Show.S01E02.1080p.WEB.h264-GRP").exists()  # planned, not moved
    assert (tmp_path / "torrent-output" / "Some.Film.1999.1080p.BluRay.x264-GRP.zip").exists()  # not unpacked either
    whats = {r["what"] for r in app.get("/api/auto").json()["log"]}
    assert "planned" in whats and "filed" not in whats and "unpacked" not in whats


def test_the_watcher_waits_for_a_running_job(app):
    import threading

    gate, started = threading.Event(), threading.Event()

    def slow(job):  # a long job of the reader's: no pick-up may start beside it or queue behind it
        started.set()
        gate.wait(5)

    app.app.state.jobs.start("memory", slow)
    started.wait(2)
    try:
        assert app.app.state.auto_look() is False
        assert app.get("/api/health").json()["busy"] is True
    finally:
        gate.set()
    _wait(app)
    assert app.app.state.auto_look() is True
    _wait(app)


def _bsdtar():
    """bsdtar where it is: the image and CI have it; Windows 10 and later ship it as tar.exe."""
    import shutil

    for tool in (shutil.which("bsdtar"), os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")):
        if tool and os.path.isfile(tool):
            out = subprocess.run([tool, "--version"], capture_output=True, text=True).stdout
            if "bsdtar" in out:
                return tool
    return None


@pytest.mark.skipif(_bsdtar() is None, reason="no bsdtar here")
def test_a_real_tar_is_listed_and_unpacked_with_bsdtar(tmp_path, monkeypatch):
    import tarfile

    monkeypatch.setattr(archives, "TOOL", _bsdtar())
    src = tmp_path / "src"
    src.mkdir()
    (src / "Some.Show.S01E09.1080p.mkv").write_bytes(b"v" * 50)
    with tarfile.open(tmp_path / "Some.Show.S01E09.1080p.WEB.tar", "w") as t:
        t.add(src / "Some.Show.S01E09.1080p.mkv", "Some.Show.S01E09.1080p.mkv")
    _old(tmp_path / "Some.Show.S01E09.1080p.WEB.tar")
    found = archives.look(str(tmp_path), "Some.Show.S01E09.1080p.WEB.tar")
    assert found.verdict == "media" and found.size == 50
    done = archives.unpack(str(tmp_path), "Some.Show.S01E09.1080p.WEB.tar", found)
    assert done["folder"] == "Some.Show.S01E09.1080p.WEB"
    assert (tmp_path / "Some.Show.S01E09.1080p.WEB" / "Some.Show.S01E09.1080p.mkv").read_bytes() == b"v" * 50
