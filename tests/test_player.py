"""The player (docs/PLAYER.md): how a video plays, .srt as WebVTT, and serving files as they are, with Range requests."""
import time

import pytest

from muthur import player
from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)


def _facts(container=".mkv", video="h264", audio=("aac",)):
    return {"container": container, "video": [{"codec": video, "width": 1920, "height": 1080, "tenBit": False, "hdr": False}],
            "audio": [{"codec": a, "channels": 6, "lang": "eng", "title": None, "default": i == 0} for i, a in enumerate(audio)],
            "embeddedSubs": 0, "duration": 6000.0}


def test_how_a_video_plays():
    assert player.playback(None) == "unknown"
    assert player.playback(_facts()) == "native"
    assert player.playback(_facts(video="hevc", audio=("eac3",))) == "sound"  # the page decodes the sound
    assert player.playback(_facts(audio=("dts",))) == "sound"
    assert player.playback(_facts(container=".avi")) == "kodi"
    assert player.playback(_facts(video="mpeg4")) == "kodi"
    assert player.playback(_facts(audio=("truehd",))) == "kodi"
    assert player.playback(_facts(audio=())) == "native"  # a silent film still plays
    two = _facts(audio=("ac3", "aac"))
    two["audio"][0]["default"], two["audio"][1]["default"] = False, True
    assert player.playback(two) == "native"  # the browser plays the default track


def test_srt_becomes_webvtt():
    srt = "1\r\n00:00:01,500 --> 00:00:04,000\r\nHallo <i>daar</i>\r\n\r\n2\r\n0:01:02,5 --> 0:01:04,25\r\nTwo\r\nlines\r\n".encode("cp1252")
    vtt = player.srt_to_vtt(srt)
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:01.500 --> 00:00:04.000\nHallo <i>daar</i>" in vtt
    assert "00:01:02.500 --> 00:01:04.250\nTwo\nlines" in vtt
    assert player.srt_to_vtt("1\n00:00:01,000 --> 00:00:02,000\nCafé\n".encode("cp1252")).endswith("Café\n")


def test_subtitles_beside_a_video_english_first(tmp_path):
    video = tmp_path / "Film (2001).mkv"
    for n in ("Film (2001).mkv", "Film (2001).nl.srt", "Film (2001).en.forced.srt", "Film (2001).en.srt", "Other.en.srt"):
        write(tmp_path / n)
    subs = player.sidecars(str(video))
    assert [s["name"] for s in subs] == ["Film (2001).en.srt", "Film (2001).en.forced.srt", "Film (2001).nl.srt"]
    assert subs[0]["label"] == "English" and subs[1]["label"] == "English (forced)"


@pytest.fixture
def client(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from muthur.web import Config, create_app

    tmp, _, _ = env
    for k, v in {"MUTHUR_CONFIG": tmp / "config", "MUTHUR_DOWNLOADS": tmp / "dl", "MUTHUR_TV": tmp / "TV", "MUTHUR_FILM": tmp / "Film",
                 "MUTHUR_QUARANTINE": tmp / "_q", "TMDB_READ_TOKEN": "x", "MUTHUR_AUTH": "0"}.items():
        monkeypatch.setenv(k, str(v))
    (tmp / "Film" / "Solaris (1972)" / "Solaris (1972).mkv").write_bytes(bytes(range(256)) * 40)
    write(tmp / "Film" / "Solaris (1972)" / "Solaris (1972).en.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    monkeypatch.setattr(player, "facts", lambda path: _facts())
    c = TestClient(create_app(Config(dotenv=False), tmdb_factory=lambda token, path: FakeTmdb()))
    c.post("/api/library/scan")
    for _ in range(200):
        if not c.get("/api/jobs/current").json()["running"]:
            break
        time.sleep(0.05)
    return c


def test_the_player_serves_videos_as_they_are(client):
    films = client.get("/api/player/items").json()["films"]
    solaris = next(f for f in films if f["title"] == "Solaris")
    vid = solaris["id"]
    info = client.get(f"/api/player/video/{vid}/info").json()
    assert info["play"] == "native" and info["path"] == "Film/Solaris (1972)/Solaris (1972).mkv"
    assert [s["name"] for s in info["subtitles"]] == ["Solaris (1972).en.srt"]
    whole = client.get(f"/api/player/video/{vid}")
    assert whole.status_code == 200 and whole.content == bytes(range(256)) * 40
    part = client.get(f"/api/player/video/{vid}", headers={"Range": "bytes=256-511"})
    assert part.status_code == 206 and part.content == bytes(range(256))  # seeking
    vtt = client.get(f"/api/player/video/{vid}/subtitles/Solaris (1972).en.srt")
    assert vtt.headers["content-type"].startswith("text/vtt") and "00:00:01.000 --> 00:00:02.000" in vtt.text
    # Only videos the index knows, and only the subtitle files beside them.
    assert client.get("/api/player/video/0123456789abcdef").status_code == 404
    sneaky = client.get(f"/api/player/video/{vid}/subtitles/..%2F..%2Fsecret.srt")  # never a file outside the video's own .srt
    assert sneaky.status_code == 404 or not sneaky.headers["content-type"].startswith("text/vtt"), sneaky.headers
    assert client.get("/api/player/items").json()["films"][0].keys() >= {"genres", "added", "play", "poster"}
