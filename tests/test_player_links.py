"""The player's 'Open with' and downloads (docs/PLAYER.md): links outside players can open, the share path, the playlist
file, a season as one ZIP, and the subtitles copied out of a file."""
import io
import zipfile

from muthur import player
from muthur.auth import Auth
from muthur.index import Index
from test_health import FakeTmdb, env, write  # noqa: F401  (the Health fixture)
from test_player import client  # noqa: F401  (the player's app, sign-in off)


def test_downloads_and_the_playlist_for_an_outside_player(client):  # noqa: F811
    vid = next(f for f in client.get("/api/player/items").json()["films"] if f["title"] == "Solaris")["id"]
    saved = client.get(f"/api/player/video/{vid}?download=1")
    assert saved.status_code == 200 and "attachment" in saved.headers["content-disposition"]
    srt = client.get(f"/api/player/video/{vid}/sidecar/Solaris (1972).en.srt?download=1")
    assert srt.status_code == 200 and srt.text.replace("\r", "").startswith("1\n00:00:01,000")  # the file itself, not WebVTT
    links = client.get(f"/api/player/video/{vid}/links").json()
    assert links["stream"].startswith(f"/api/player/video/{vid}?key=") and links["share"] is None  # the share isn't known yet
    playlist = client.get(f"/api/player/video/{vid}/playlist.m3u").text  # before muthur knows the share: its own link
    assert playlist.startswith("#EXTM3U") and f"/api/player/video/{vid}?key=" in playlist


def test_a_share_path_never_carries_kodis_password():
    where = player.share_paths("smb://kodi:secret@nostromo/Iedereen/Film/", "Dune (2021)/Dune (2021).mkv")
    assert where == {"smb": "smb://nostromo/Iedereen/Film/Dune (2021)/Dune (2021).mkv",
                     "unc": "\\\\nostromo\\Iedereen\\Film\\Dune (2021)\\Dune (2021).mkv"}
    assert player.share_paths(None, "x.mkv") is None and player.share_paths("nfs://nas/x/", "y.mkv") is None


def test_a_season_downloads_as_one_zip(tmp_path):
    a, b = tmp_path / "S01E01.mkv", tmp_path / "S01E01.en.srt"
    a.write_bytes(bytes(range(256)) * 9000)  # more than one read block
    b.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    data = b"".join(player.zip_stream([("Show/S01E01.mkv", str(a)), ("Show/S01E01.en.srt", str(b))], chunk=4096))
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.namelist() == ["Show/S01E01.mkv", "Show/S01E01.en.srt"] and z.read("Show/S01E01.mkv") == a.read_bytes()
    assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())  # packed, not compressed


def test_which_subtitles_are_copied_out_of_a_file(tmp_path):
    video = tmp_path / "Film (2008).mkv"
    write(video)
    tracks = [{"index": 2, "lang": "en", "title": "", "forced": False, "sdh": False},
              {"index": 3, "lang": "fr", "title": "Ch'ti", "forced": False, "sdh": False},
              {"index": 4, "lang": "en", "title": "SDH", "forced": False, "sdh": True},
              {"index": 5, "lang": "nl", "title": "", "forced": False, "sdh": False}]
    assert [n for _, n in player.to_extract(str(video), tracks)] == ["Film (2008).en.srt", "Film (2008).sdh.en.srt"]
    assert [n for _, n in player.to_extract(str(video), [tracks[1], tracks[3]])] == ["Film (2008).nl.srt"]  # Dutch only without English
    write(tmp_path / "Film (2008).en.srt")
    assert player.to_extract(str(video), tracks) == []  # English is there already


def test_a_link_key_opens_one_video_without_the_sign_in(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from muthur.web import Config, create_app

    tmp, _, _ = env
    for k, v in {"MUTHUR_CONFIG": tmp / "config", "MUTHUR_DOWNLOADS": tmp / "dl", "MUTHUR_TV": tmp / "TV", "MUTHUR_FILM": tmp / "Film",
                 "MUTHUR_QUARANTINE": tmp / "_q", "TMDB_READ_TOKEN": "x", "MUTHUR_AUTH": "1"}.items():
        monkeypatch.setenv(k, str(v))
    (tmp / "Film" / "Solaris (1972)" / "Solaris (1972).mkv").write_bytes(b"video")
    app = create_app(Config(dotenv=False), tmdb_factory=lambda token, path: FakeTmdb())
    store = app.state.store
    store.save_snapshot("library", Index(store, str(tmp / "TV"), str(tmp / "Film")).build())
    c = TestClient(app)
    vid = player.file_id("Film/Solaris (1972)/Solaris (1972).mkv")
    key = Auth(store).link_key(vid)
    assert c.get(f"/api/player/video/{vid}").status_code == 401  # no sign-in, no key
    assert c.get(f"/api/player/video/{vid}?key={key}").content == b"video"
    assert c.get(f"/api/player/video/{vid}?key={key}x").status_code == 401  # a changed key
    other = player.file_id("Film/Mystery/Mystery.mkv")
    assert c.get(f"/api/player/video/{other}?key={key}").status_code == 401  # only the video it was made for
    assert c.get(f"/api/player/items?key={key}").status_code == 401  # and nothing else
    old = Auth(store).link_key(vid, seconds=-5)
    assert c.get(f"/api/player/video/{vid}?key={old}").status_code == 401  # expired
