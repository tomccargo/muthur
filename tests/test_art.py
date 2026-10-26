"""Poster checks: sizes read from the file's header, and Health replacing a missing or poor poster."""
import struct

from test_health import env  # noqa: F401  (the Health fixture)

from muthur.art import image_size, poster_problem


def jpeg(w: int, h: int, thumb: tuple[int, int] | None = None) -> bytes:
    """A JPEG header: an EXIF block (with its own small picture, as cameras write) and then the frame's size."""
    out = b"\xff\xd8"
    if thumb:
        inner = b"Exif\x00\x00" + b"\xff\xd8\xff\xc0\x00\x11\x08" + struct.pack(">HH", thumb[1], thumb[0]) + b"\x00" * 10
        out += b"\xff\xe1" + struct.pack(">H", len(inner) + 2) + inner
    return out + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, w) + b"\x03" + b"\x00" * 9 + b"\xff\xd9"


def png(w: int, h: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


def test_sizes_come_from_the_picture_not_its_thumbnail(tmp_path):
    p = tmp_path / "poster.jpg"
    p.write_bytes(jpeg(780, 1170, thumb=(109, 160)))
    assert image_size(str(p)) == (780, 1170) and poster_problem(str(p)) is None
    p.write_bytes(jpeg(444, 666))
    assert poster_problem(str(p)) == "444×666, too small"
    p.write_bytes(jpeg(600, 800))
    assert poster_problem(str(p)) == "600×800, not poster-shaped"
    p.write_bytes(png(1000, 1500))
    assert image_size(str(p)) == (1000, 1500)
    p.write_bytes(b"not a picture")
    assert poster_problem(str(p)) == "not a picture muthur can read"


def test_health_replaces_a_poor_poster_and_can_put_it_back(env):  # noqa: F811
    tmp, health, _ = env
    show = tmp / "TV" / "Some Show"
    (show / "poster.jpg").write_bytes(jpeg(400, 578))
    health.tmdb.tv = lambda i: {"id": i, "name": "Some Show", "poster_path": "/p.jpg", "seasons": [{"season_number": 1, "episode_count": 3}]}
    plan = health.check(health.index.build())
    [fix] = [x for x in plan["fixes"]["posters"] if x["path"].startswith("TV/Some Show")]
    assert fix["why"] == "400×578, too small" and fix["nfo"] == "TV/Some Show/tvshow.nfo"
    result = health.apply({"fixes": {"posters": [fix]}}, ["posters"])
    assert result["failed"] == [] and (show / "poster.jpg").read_bytes() == b"img"  # TMDB's (the fake's) poster
    health.journal.undo(result["run"])
    assert image_size(str(show / "poster.jpg")) == (400, 578)
