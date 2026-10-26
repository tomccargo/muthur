"""The player (docs/PLAYER.md): what the library holds for watching, how each video plays in a browser, and its
.srt subtitles as WebVTT. Read-only: the files stay exactly as they are.

A video plays one of three ways, from its container and codecs:
- 'native': the browser plays picture and sound itself;
- 'sound': the browser plays the picture, and the page decodes the sound itself (AC-3, E-AC-3, DTS: Mediabunny);
- 'kodi': no browser plays it (AVI, XviD, MPEG-2...): it stays a Kodi thing.
H.264 in 10-bit plays in Chrome and Edge but not in Firefox (measured 26 Oct): its class ends in '-hi10' and the page
decides by the browser it runs in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess

from .subtitles import kind as sub_kind

SCHEMA = "CREATE TABLE IF NOT EXISTS play_cache (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL, body TEXT NOT NULL);"
CONTAINERS = {".mkv", ".mp4", ".m4v", ".webm", ".mov"}
VIDEO = {"h264", "hevc", "av1", "vp9", "vp8"}
AUDIO = {"aac", "mp3", "opus", "vorbis", "flac"}
DECODED = {"ac3", "eac3", "dts"}  # the page decodes these itself
LANG_NAMES = {"en": "English", "nl": "Dutch", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "ja": "Japanese"}


def file_id(path: str) -> str:
    """A stable id for a library path ('TV/Show/Season 1/x.mkv'): the browser never sends a path."""
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


def facts(path: str) -> dict | None:
    """The container and every video and audio stream, in file order, from ffprobe (it reads the headers only)."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration:stream=index,codec_type,codec_name,profile,pix_fmt,color_transfer,width,height,channels:"
                              "stream_disposition=default,attached_pic:stream_tags=language,title",
                              "-of", "json", path], capture_output=True, text=True, timeout=120).stdout
        data = json.loads(out or "{}")
    except (subprocess.SubprocessError, ValueError):
        return None
    video, audio, subs = [], [], 0
    for s in data.get("streams") or []:
        disp, tags = s.get("disposition") or {}, s.get("tags") or {}
        if s.get("codec_type") == "video" and not disp.get("attached_pic"):
            video.append({"codec": s.get("codec_name"), "width": s.get("width") or 0, "height": s.get("height") or 0,
                          "tenBit": "10" in (s.get("pix_fmt") or ""), "hdr": s.get("color_transfer") in ("smpte2084", "arib-std-b67")})
        elif s.get("codec_type") == "audio":
            audio.append({"codec": s.get("codec_name"), "channels": s.get("channels") or 0, "lang": tags.get("language"),
                          "title": tags.get("title"), "default": bool(disp.get("default"))})
        elif s.get("codec_type") == "subtitle":
            subs += 1
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {"container": os.path.splitext(path)[1].lower(), "video": video, "audio": audio, "embeddedSubs": subs, "duration": duration}


def playback(f: dict | None) -> str:
    """'native', 'sound', 'kodi', or 'unknown' when the file wasn't read yet; 'native-hi10' or 'sound-hi10' for H.264
    in 10-bit, which only some browsers play."""
    if not f:
        return "unknown"
    if f["container"] not in CONTAINERS or not f["video"] or f["video"][0]["codec"] not in VIDEO:
        return "kodi"
    audio = main_audio(f)
    way = "native" if audio is None or audio["codec"] in AUDIO else "sound" if audio["codec"] in DECODED else "kodi"
    hi10 = f["video"][0]["codec"] == "h264" and f["video"][0]["tenBit"]
    return f"{way}-hi10" if hi10 and way != "kodi" else way


# ISO 639-1 (TMDB's original_language) -> the ISO 639-2 codes files tag their tracks with (B and T forms).
ISO2 = {"en": ["eng"], "nl": ["dut", "nld"], "fr": ["fre", "fra"], "de": ["ger", "deu"], "es": ["spa"], "it": ["ita"], "ja": ["jpn"],
        "ko": ["kor"], "zh": ["chi", "zho"], "cn": ["chi", "zho"], "ru": ["rus"], "pt": ["por"], "sv": ["swe"], "da": ["dan"],
        "no": ["nor", "nob", "nno"], "nb": ["nob", "nor"], "fi": ["fin"], "pl": ["pol"], "cs": ["cze", "ces"], "hu": ["hun"],
        "tr": ["tur"], "el": ["gre", "ell"], "he": ["heb"], "ar": ["ara"], "hi": ["hin"], "th": ["tha"], "is": ["ice", "isl"],
        "ro": ["rum", "ron"], "uk": ["ukr"], "fa": ["per", "fas"], "id": ["ind"], "ta": ["tam"], "te": ["tel"], "ga": ["gle"]}


def audio_pick(f: dict | None, original: str | None) -> int | None:
    """Which audio track to play: the first in the original language (docs/PLAYER.md §4), else the default one. An
    index into the file's audio tracks, in file order; None without audio."""
    if not f or not f["audio"]:
        return None
    codes = ISO2.get(original or "", [original] if original else [])
    for i, a in enumerate(f["audio"]):
        if a.get("lang") in codes:
            return i
    default = main_audio(f)
    return f["audio"].index(default) if default else 0


def main_audio(f: dict) -> dict | None:
    """The track a browser plays: the first one marked default, else the first."""
    return next((a for a in f["audio"] if a["default"]), f["audio"][0] if f["audio"] else None)


class Facts:
    """facts(), cached by path, size and modification time, so each file is read once."""

    def __init__(self, store):
        self.store = store
        with store.lock:
            store.db.execute(SCHEMA)
            store.db.commit()

    def cached(self, full: str) -> dict | None:
        try:
            st = os.stat(full)
        except OSError:
            return None
        with self.store.lock:
            row = self.store.db.execute("SELECT size, mtime, body FROM play_cache WHERE path = ?", (full,)).fetchone()
        return json.loads(row[2]) if row and row[0] == st.st_size and row[1] == st.st_mtime else None

    def get(self, full: str) -> dict | None:
        if (known := self.cached(full)) is not None:
            return known
        found = facts(full)
        if found is not None:
            st = os.stat(full)
            with self.store.lock:
                self.store.db.execute("INSERT OR REPLACE INTO play_cache VALUES (?, ?, ?, ?)", (full, st.st_size, st.st_mtime, json.dumps(found)))
                self.store.db.commit()
        return found


# -- the catalogue ---------------------------------------------------------------------------------------------------
def catalogue(lib: dict) -> dict[str, str]:
    """id -> library path, for every video the index knows."""
    out = {}
    for sh in lib.get("shows", []):
        for e in sh["episodes"]:
            p = f"TV/{sh['folder']}/{e['file']}"
            out[file_id(p)] = p
    for f in lib.get("films", []):
        if f.get("file"):
            out[file_id(f"Film/{f['file']}")] = f"Film/{f['file']}"
    return out


def film_dir(f: dict) -> str | None:
    """The folder that holds a film's video, poster and fanart ('X (1999)' or 'X (1999)/X (1999)'), relative to Film."""
    return f["file"].rsplit("/", 1)[0] if f.get("file") and "/" in f["file"] else None


def items(lib: dict, play_of) -> dict:
    """The grid: shows and films with what the player filters and sorts on. play_of(library path) -> playback class."""
    shows = []
    for sh in lib.get("shows", []):
        eps = [e for e in sh["episodes"] if not e.get("sample")]
        if not eps:
            continue
        shows.append({"folder": sh["folder"], "title": sh["title"], "year": sh["year"], "genres": genres(sh),
                      "rating": _score(sh), "poster": f"TV/{sh['folder']}/poster.jpg" if sh["poster"] else None,
                      "fanart": f"TV/{sh['folder']}/fanart.jpg" if sh.get("fanart") else None,
                      "episodes": len(eps), "watched": sum(1 for e in eps if e["watched"]),
                      "seasons": len({e["season"] for e in eps if e["season"] is not None}),
                      "added": max((e.get("added", 0) for e in eps), default=0)})
    films = []
    for f in lib.get("films", []):
        if not f.get("file"):
            continue
        d = film_dir(f)
        path = f"Film/{f['file']}"
        films.append({"id": file_id(path), "key": f["key"], "title": f["title"], "year": f["year"], "genres": genres(f),
                      "rating": _score(f), "plot": f.get("plot"), "watched": bool(f["watched"]), "added": f.get("added", 0),
                      "poster": f"Film/{f['posterFile']}" if f.get("posterFile") else f"Film/{d}/poster.jpg" if d and f["poster"] else None,
                      "fanart": f"Film/{d}/fanart.jpg" if d else None, "play": play_of(path)})
    return {"at": lib.get("at"), "shows": shows, "films": films}


def show(lib: dict, folder: str, play_of) -> dict | None:
    """One show's seasons and episodes for the player."""
    sh = next((s for s in lib.get("shows", []) if s["folder"] == folder), None)
    if sh is None:
        return None
    eps = []
    for e in sh["episodes"]:
        if e.get("sample"):
            continue
        path = f"TV/{folder}/{e['file']}"
        stem = e["file"].rsplit(".", 1)[0]
        eps.append({"id": file_id(path), "season": e["season"], "episodes": e["episodes"], "title": e["title"],
                    "watched": bool(e["watched"]), "added": e.get("added", 0),
                    "thumb": f"TV/{folder}/{stem}-thumb.jpg" if e.get("thumb") else None, "play": play_of(path)})
    eps.sort(key=lambda x: (x["season"] if x["season"] is not None else 999, x["episodes"][:1] or [0]))
    return {"folder": folder, "title": sh["title"], "year": sh["year"], "genres": genres(sh), "plot": sh.get("plot"),
            "rating": _score(sh), "poster": f"TV/{folder}/poster.jpg" if sh["poster"] else None,
            "fanart": f"TV/{folder}/fanart.jpg" if sh.get("fanart") else None, "episodes": eps}


# NFOs from Dutch or German scrapers name genres in their language: one name per genre in the filters.
GENRE_NAMES = {"avontuur": "Adventure", "komedie": "Comedy", "komödie": "Comedy", "familie": "Family", "romantiek": "Romance",
               "romantik": "Romance", "misdaad": "Crime", "krimi": "Crime", "documentaire": "Documentary", "dokumentarfilm": "Documentary",
               "oorlog": "War", "krieg": "War", "geschiedenis": "History", "historie": "History", "muziek": "Music", "musik": "Music",
               "animatie": "Animation", "zeichentrick": "Animation", "sciencefiction": "Science Fiction", "sci-fi": "Science Fiction",
               "sci-fi & fantasy": "Science Fiction", "action & adventure": "Action", "thriller": "Thriller", "horror": "Horror",
               "mysterie": "Mystery", "fantasie": "Fantasy", "abenteuer": "Adventure", "drama": "Drama", "western": "Western"}
NOT_GENRES = {"serie", "series", "tv movie", "problem"}


def genres(x: dict) -> list[str]:
    out = []
    for g in x.get("genres", []):
        low = g.strip().lower()
        if low in NOT_GENRES:
            continue
        name = GENRE_NAMES.get(low, g.strip())
        if name not in out:
            out.append(name)
    return out


def _score(x: dict) -> float | None:
    """The score to show: IMDb's when the NFO has it, else the one Kodi shows."""
    if x.get("imdb"):
        return x["imdb"][0]
    r = x.get("rating")
    return r[1] if r else None


# -- subtitles -------------------------------------------------------------------------------------------------------
def sidecars(full: str) -> list[dict]:
    """The .srt files beside a video, named for it ('x.en.srt', 'x.srt'), English first."""
    folder, name = os.path.split(full)
    stem = os.path.splitext(name)[0]
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".srt") and n.startswith(stem + ".") or n == stem + ".srt")
    except OSError:
        return []
    out = []
    for n in names:
        lang, forced, sdh = sub_kind(n[len(stem):])
        label = LANG_NAMES.get(lang or "", (lang or "Subtitles").upper() if lang else "Subtitles")
        out.append({"name": n, "lang": lang or "und", "label": label + (" (forced)" if forced else "") + (" (SDH)" if sdh else ""),
                    "forced": forced})
    return sorted(out, key=lambda s: (s["lang"] != "en", s["forced"], s["label"]))


TIME = re.compile(r"(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})")


def srt_to_vtt(raw: bytes) -> str:
    """An .srt as WebVTT: the same cues and timings; the character set guessed (UTF-8, else Windows-1252)."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = ["WEBVTT", ""]
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]  # the cue number: WebVTT doesn't need it
        if not lines or "-->" not in lines[0]:
            continue
        lines[0] = TIME.sub(lambda m: f"{m.group(1).zfill(8)}.{m.group(2).ljust(3, '0')}", lines[0])
        out += [*lines, ""]
    return "\n".join(out)
