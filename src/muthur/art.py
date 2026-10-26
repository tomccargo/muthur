"""Artwork checks: how big an image is, and whether it makes a decent poster."""
from __future__ import annotations

import struct

MIN_WIDTH = 500  # TMDB's posters are 780 wide at muthur's size; old ones from other scrapers can be 300-400
SHAPE = (1.35, 1.6)  # height / width: a poster is 2:3 (1.5); 3:4 (1.33) is a cover or a screenshot


def image_size(path: str) -> tuple[int, int] | None:
    """(width, height) of a JPEG or PNG from its header, or None when it can't be read."""
    try:
        with open(path, "rb") as f:
            data = f.read(512 * 1024)
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):  # start of frame: the picture's own size, not an EXIF thumbnail's
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def poster_problem(path: str) -> str | None:
    """Why this file is a poor poster ('444×666, too small'), or None when it is fine."""
    size = image_size(path)
    if size is None:
        return "not a picture muthur can read"
    w, h = size
    if w < MIN_WIDTH:
        return f"{w}×{h}, too small"
    if not SHAPE[0] <= h / w <= SHAPE[1]:
        return f"{w}×{h}, not poster-shaped"
    return None
