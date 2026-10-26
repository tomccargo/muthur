"""Does an .srt beside a video fit it? (docs/PLAYER.md, decided 26 Oct.) A subtitle file from another release can be
shifted (an intro cut differently) or run at another speed (made for 25 fps while the video runs at 23.976: 4% fast,
minutes off by the end). When the video carries subtitles of its own in the same language, those fit it by
definition: muthur reads a few minutes of them at three points in the film, matches the spoken lines, and fits
'time in the video = shift + speed x time in the file'. A file that only has a shift or a speed problem can be
stretched to fit; one that is cut differently can't.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

WINDOWS = (0.2, 0.5, 0.8)  # where in the film to read, as a share of its length
WINDOW = 300  # seconds read at each (a quiet film says few lines)
TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")
FITS = 0.6  # seconds: closer than this everywhere, the file fits
MIN_PAIRS = 8


def _seconds(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def _words(lines: list[str]) -> str:
    return " ".join(re.sub(r"<[^>]+>|\{[^}]*\}|[^a-z0-9 ]", "", " ".join(lines).lower()).split())


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def cues(text: str) -> list[tuple[float, str]]:
    """(start in seconds, the line's words) for every cue of an .srt with at least four words."""
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if m := TIME.search(line):
                words = _words(lines[i + 1:])
                if len(words.split()) >= 4:
                    out.append((_seconds(*m.groups()[:4]), words))
                break
    return out


def sample(full: str, index: int, duration: float) -> list[tuple[float, str]]:
    """The cues of the video's own subtitle track (stream `index`) in three windows, with the video's own times."""
    if not shutil.which("ffmpeg") or duration <= 0:
        return []
    found: list[tuple[float, str]] = []
    for share in WINDOWS:
        start = round(max(0.0, duration * share), 1)
        # -ss before -i: ffmpeg jumps there through the file's index. -copyts keeps the film's own times (without it they
        # count from the key frame before the window, seconds off), and -to as an output option ends the window (an
        # input -t doesn't stop a subtitle track: measured on Dune).
        try:
            out = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start}", "-copyts", "-i", full, "-map", f"0:{index}",
                                  "-to", f"{start + WINDOW}", "-c:s", "srt", "-f", "srt", "pipe:1"], capture_output=True, timeout=300).stdout
        except subprocess.SubprocessError:
            continue
        found += cues(decode(out))
    return found


def fit(reference: list[tuple[float, str]], theirs: list[tuple[float, str]]) -> dict | None:
    """Shift and speed that map the file's times onto the video's, from the lines both have: {pairs, shift, speed,
    error (median seconds left after the fit), off (largest difference before it)}. None: too few lines in common."""
    by_text: dict[str, list[float]] = {}
    for t, w in theirs:
        by_text.setdefault(w, []).append(t)
    pairs = sorted((by_text[w][0], t) for t, w in reference if len(by_text.get(w, [])) == 1)  # lines said once only
    if len(pairs) < MIN_PAIRS:
        return None
    med = lambda v: sorted(v)[len(v) // 2]  # noqa: E731
    # Robust against a few lines matched wrongly (a download site's notice, a repeated phrase): the median difference
    # per window, then the line through those points.
    groups: list[list[tuple[float, float]]] = []
    for p in pairs:
        if groups and p[0] - groups[-1][-1][0] < WINDOW * 2:
            groups[-1].append(p)
        else:
            groups.append([p])
    points = [(med([x for x, _ in g]), med([y - x for x, y in g])) for g in groups if len(g) >= 3]
    if len(points) >= 2:
        (x1, d1), (x2, d2) = points[0], points[-1]
        slope = (d2 - d1) / (x2 - x1) if x2 != x1 else 0.0  # the difference grows by this much per second
        speed, shift = 1 + slope, d1 - slope * x1
    else:
        speed, shift = 1.0, med([y - x for x, y in pairs])
    return {"pairs": len(pairs), "shift": round(shift, 3), "speed": round(speed, 6),
            "error": round(med([abs(shift + speed * x - y) for x, y in pairs]), 3), "off": round(med([abs(y - x) for x, y in pairs]), 2)}


def verdict(f: dict | None) -> str | None:
    """'fits', 'stretch' (only shifted or at another speed), 'cut' (doesn't fit, can't be stretched), None (can't tell)."""
    if f is None:
        return None
    if f["off"] <= FITS:
        return "fits"
    return "stretch" if f["error"] <= FITS and 0.9 < f["speed"] < 1.1 else "cut"


def retime(raw: bytes, shift: float, speed: float) -> bytes:
    """The same .srt with every time moved to 'shift + speed x time' (never below zero)."""
    def stamp(t: float) -> str:
        t = max(0.0, t)
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    def move(m: re.Match) -> str:
        a, b = _seconds(*m.groups()[:4]), _seconds(*m.groups()[4:])
        return f"{stamp(shift + speed * a)} --> {stamp(shift + speed * b)}"

    text = decode(raw)
    newline = "\r\n" if "\r\n" in text else "\n"
    return TIME.sub(move, text).replace("\r\n", "\n").replace("\n", newline).encode("utf-8")


SCHEMA = "CREATE TABLE IF NOT EXISTS sub_fit (srt TEXT PRIMARY KEY, stamp TEXT NOT NULL, body TEXT NOT NULL);"


class SubFit:
    """fit() per .srt beside a video, cached until the .srt or the video changes: each file is measured once."""

    def __init__(self, store):
        self.store = store
        with store.lock:
            store.db.execute(SCHEMA)
            store.db.commit()

    @staticmethod
    def _stamp(srt: str, video: str) -> str:
        a, b = os.stat(srt), os.stat(video)
        return f"{a.st_size}:{a.st_mtime}:{b.st_size}:{b.st_mtime}"

    def check(self, video: str, duration: float, beside: list[dict], inside) -> list[dict]:
        """For each .srt beside the video (as player.sidecars) that has a track inside the video in its language (a file
        without a language counts as English): {name, verdict, fit}. inside(): the video's text tracks (player.embedded),
        asked only when a file wasn't measured yet: a Health check that finds nothing new doesn't read the videos at all
        (it took ages on 26 Oct, asking ffprobe for 2,790 videos every time)."""
        refs: dict[str, list] = {}
        tracks: list[dict] | None = None
        out = []
        for s in beside:
            if s["forced"]:
                continue  # forced lines are too few to match
            srt = os.path.join(os.path.dirname(video), s["name"])
            try:
                stamp = self._stamp(srt, video)
            except OSError:
                continue
            with self.store.lock:
                row = self.store.db.execute("SELECT stamp, body FROM sub_fit WHERE srt = ?", (srt,)).fetchone()
            if row and row[0] == stamp:
                found = json.loads(row[1])
            else:
                lang = "en" if s["lang"] == "und" else s["lang"]
                tracks = inside() if tracks is None else tracks
                track = next((t for t in tracks if t["lang"] == lang and not t["forced"]), None)
                if track is None:
                    found = {"verdict": None, "fit": None}  # nothing inside to compare with: remembered as such
                else:
                    if lang not in refs:
                        refs[lang] = sample(video, track["index"], duration)
                    with open(srt, "rb") as fh:
                        f = fit(refs[lang], cues(decode(fh.read())))
                    found = {"verdict": verdict(f), "fit": f}
                with self.store.lock:
                    self.store.db.execute("INSERT OR REPLACE INTO sub_fit VALUES (?, ?, ?)", (srt, stamp, json.dumps(found)))
                    self.store.db.commit()
            if found["verdict"]:
                out.append({"name": s["name"], **found})
        return out


def describe(f: dict) -> str:
    """'4.3% too fast, 0.4 s late' for a fix's line in Health."""
    parts = []
    if abs(f["speed"] - 1) >= 0.001:
        parts.append(f"{abs(f['speed'] - 1) * 100:.1f}% too {'fast' if f['speed'] > 1 else 'slow'}")
    if abs(f["shift"]) >= 0.3:
        parts.append(f"{abs(f['shift']):.1f} s too {'early' if f['shift'] > 0 else 'late'}")
    return ", ".join(parts) or "a little off"
