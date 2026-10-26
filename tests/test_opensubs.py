"""Subtitles from OpenSubtitles.com, searched per video and chosen by the reader (no network: the API is faked)."""
import struct

import pytest

from muthur.opensubs import OpenSubtitles, moviehash, release_match
from muthur.store import Store


def test_the_fingerprint_is_size_plus_the_sums_of_the_first_and_last_64_kb(tmp_path):
    p = tmp_path / "x.mkv"
    head, tail = bytes(range(256)) * 256, bytes(reversed(range(256))) * 256
    p.write_bytes(head + b"\0" * 1000 + tail)
    expected = p.stat().st_size
    for block in (head, tail):
        for (n,) in struct.iter_unpack("<Q", block):
            expected = (expected + n) & 0xFFFFFFFFFFFFFFFF
    assert moviehash(str(p)) == f"{expected:016x}"
    (tmp_path / "small.mkv").write_bytes(b"x" * 100)
    assert moviehash(str(tmp_path / "small.mkv")) is None  # too small to have one


def test_what_a_release_shares_with_the_file():
    file = "Bad.Sisters.S01E01.1080p.WEBRip.x265-RARBG.mp4"
    assert release_match("Bad.Sisters.S01E01.1080p.WEBRip.x265-RARBG", file) == ["group RARBG", "1080p", "WEBRip"]
    assert release_match("Bad Sisters S01E01 720p HDTV x264-SYNCOPY", file) == []


class Reply:
    def __init__(self, status, body=None, content=b""):
        self.status_code, self._body, self.content = status, body, content

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def sub(file_id, release, lang="en", **extra):
    return {"attributes": {"language": lang, "release": release, "download_count": extra.get("downloads", 0),
                           "moviehash_match": extra.get("hash", False), "hearing_impaired": extra.get("hi", False),
                           "files": [{"file_id": file_id, "file_name": release + ".srt"}]}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    os_ = OpenSubtitles("key", "me", "pw", Store(str(tmp_path / "db.sqlite")))
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(("get", url, dict(params or [])))
        if url.endswith("/subtitles"):
            return Reply(200, {"data": [sub(1, "Show.S01E01.720p.HDTV-LOL", downloads=900), sub(2, "Show.S01E01.1080p.WEB-DL-NTb", downloads=10),
                                        sub(3, "Show.S01E01.1080p.WEB-DL-NTb", hash=True, downloads=1), sub(4, "Show S01E01", lang="nl", downloads=5000)]})
        return Reply(200, content=b"1\n00:00:01,000 --> 00:00:02,000\nHello\n")

    def post(url, json=None, headers=None, timeout=None):
        calls.append(("post", url, json))
        if url.endswith("/login"):
            return Reply(200, {"token": "jwt", "user": {"allowed_downloads": 20, "level": "Sub leecher", "vip": False}})
        return Reply(200, {"link": "https://dl.example/x.srt", "remaining": 19})

    monkeypatch.setattr(os_.session, "get", get)
    monkeypatch.setattr(os_.session, "post", post)
    return os_, calls


def test_results_put_the_files_own_fingerprint_first_then_its_release(client, tmp_path):
    os_, calls = client
    video = tmp_path / "Show.S01E01.1080p.WEB-DL-NTb.mkv"
    video.write_bytes(b"v" * 200000)
    got = os_.search(parent_imdb_id="tt0123", season=1, episode=1, video=str(video))
    assert [s["fileId"] for s in got] == [3, 2, 1, 4]  # fingerprint, same release, then English before Dutch
    params = calls[0][2]
    assert params["parent_imdb_id"] == 123 and params["season_number"] == 1 and params["episode_number"] == 1 and len(params["moviehash"]) == 16


def test_a_download_logs_in_once_and_says_what_is_left(client):
    os_, calls = client
    data, remaining = os_.download(3)
    assert data.startswith(b"1\n") and remaining == 19
    os_.download(2)
    assert [c[1].rsplit("/", 1)[1] for c in calls if c[0] == "post"] == ["login", "download", "download"]  # the token is kept
