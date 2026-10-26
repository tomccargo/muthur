"""Subtitles Kodi can't find, and where they belong.

Kodi 21 (CUtil::ScanForExternalSubtitles) looks beside the video and one level into a folder named
subs, subtitles, sub, vobsub, vobsubs or subtitle, and only takes files whose name starts with the
video's; the language is a word after that name ('x.en.srt', 'x.English.srt'). So 'Subs/x/2_English.srt'
(how RARBG ships them) or '28.Days.Later.(2002).English.srt' beside '28 Days Later (2002).mkv' is never
shown. plan() pairs such subtitles with their video: English and Dutch go beside it under its name, other
languages and ones the video already has go to quarantine, and those whose video is gone are leftovers.
"""
from __future__ import annotations

import os
import re

from .parse import SAMPLE, is_video

SUBTITLES = (".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup", ".smi")
KODI_DIRS = {"subs", "subtitles", "vobsubs", "sub", "vobsub", "subtitle"}
KEEP = ("en", "nl")  # the languages moved beside the video; the rest is set aside
NUMBERS = re.compile(r"(?i)\bs(\d{1,3})[ ._-]?e(\d{1,3})")
SKIP = ("@", ".", "#")
_L = {
    "en": "english eng en", "nl": "dutch nederlands flemish vlaams nld dut nl", "fr": "french francais fre fra fr",
    "de": "german deutsch ger deu de", "es": "spanish espanol spa es", "it": "italian italiano ita it",
    "pt": "portuguese por pt pt-br", "sv": "swedish svenska swe sv", "da": "danish dansk dan da",
    "no": "norwegian norsk nor nob no", "fi": "finnish suomi fin fi", "pl": "polish polski pol pl",
    "cs": "czech cze ces cs", "hu": "hungarian hun hu", "ro": "romanian rum ron ro", "tr": "turkish tur tr",
    "el": "greek gre ell el", "ru": "russian rus ru", "uk": "ukrainian ukr uk", "ja": "japanese jpn ja",
    "ko": "korean kor ko", "zh": "chinese chi zho zh chs cht", "ar": "arabic ara ar", "he": "hebrew heb he",
    "hr": "croatian hrv hr", "sr": "serbian srp sr", "sl": "slovenian slv sl", "bg": "bulgarian bul bg",
    "id": "indonesian ind", "ms": "malay msa", "th": "thai tha th", "vi": "vietnamese vie vi", "hi": "hindi hin",
    "et": "estonian est et", "lv": "latvian lav lv", "lt": "lithuanian lit lt", "is": "icelandic ice isl",
}
LANGUAGES = {word: code for code, words in _L.items() for word in words.split()}  # 'English' -> 'en'


def language(name: str) -> str | None:
    """The language a subtitle's name gives, from its last language word: '2_English' en, 'x.nl.sdh' nl, 'x' None."""
    for t in reversed(re.split(r"[\s._\-\[\]()]+", name.lower())):
        if t in LANGUAGES and t != "hi":  # 'hi' is a hearing-impaired tag far more often than Hindi
            return LANGUAGES[t]
    return None


def _kind(name: str) -> tuple[str | None, bool, bool]:
    """(language, forced, for the hard of hearing) from a subtitle's name."""
    tokens = set(re.split(r"[\s._\-\[\]()]+", name.lower()))
    return language(name), "forced" in tokens, bool(tokens & {"sdh", "cc", "hi"})


def _new_name(stem: str, lang: str | None, forced: bool, sdh: bool) -> list[str]:
    """'x.sdh.en.forced': Kodi 21 reads the name from the right, takes 'forced' (and 'default') as flags and the
    first word it knows as the language, so 'sdh' goes before the language and 'hi' (Hindi to Kodi) never appears."""
    return [stem, *(["sdh"] if sdh else []), *([lang] if lang else []), *(["forced"] if forced else [])]


def plan(lib: str, root: str, unit: str) -> tuple[list[dict], list[dict]]:
    """(fixes, leftovers) for the subtitles Kodi can't find in one show or film folder ('TV', '/data/Series',
    'The Wire'), as library paths ('TV/The Wire/Season 1/x.srt'). A fix is one video:
    {'path', 'label', 'move': [[from, to]], 'drop': [path], 'dirs': [path], 'why'}. Only shows have leftovers:
    a film folder's subtitle muthur can't pair stays where it is."""
    tv = lib == "TV"
    videos: dict[str, list[str]] = {}  # folder (relative to the root) -> video names without extension
    subs: list[tuple[str, str]] = []  # (folder, file)
    for dirpath, dirnames, names in os.walk(os.path.join(root, unit)):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(SKIP))
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        for n in sorted(names):
            if is_video(n) and not SAMPLE.search(n):
                videos.setdefault(rel, []).append(os.path.splitext(n)[0])
            elif n.lower().endswith(SUBTITLES):
                subs.append((rel, n))
    if not subs:
        return [], []
    every = [(d, s) for d, stems in videos.items() for s in stems]

    def kodi_finds(folder: str, name: str) -> bool:
        places = [folder] + ([folder.rsplit("/", 1)[0]] if "/" in folder and folder.rsplit("/", 1)[1].lower() in KODI_DIRS else [])
        return any(name.lower().startswith(s.lower()) for p in places for s in videos.get(p, []))

    def owner(folder: str, name: str) -> tuple[str, str] | None:
        bare, here = os.path.splitext(name)[0].lower(), folder.rsplit("/", 1)[-1].lower()
        for d, s in every:  # 'Subs/<video>/2_English.srt'
            if here == s.lower():
                return d, s
        named = [(d, s) for d, s in every if bare.startswith(s.lower())]  # named after it, in the wrong place
        if named:
            return max(named, key=lambda v: len(v[1]))
        if tv:
            m = NUMBERS.search(name) or NUMBERS.search(folder.rsplit("/", 1)[-1])
            if m:
                same = [(d, s) for d, s in every if (n := NUMBERS.search(s)) and (int(n.group(1)), int(n.group(2))) == (int(m.group(1)), int(m.group(2)))]
                return same[0] if len(same) == 1 else None
            return None
        return every[0] if len(every) == 1 else None  # a film folder with one video

    have: dict[tuple[str, str], set] = {}  # (language, forced) Kodi already finds for each video
    for folder, name in subs:
        if kodi_finds(folder, name):
            for d, s in every:
                if name.lower().startswith(s.lower()) and d in (folder, folder.rsplit("/", 1)[0]):
                    lang, forced, _ = _kind(os.path.splitext(name)[0][len(s):])
                    have.setdefault((d, s), set()).add((lang, forced))
    per_video: dict[tuple[str, str], dict] = {}
    leftovers: list[dict] = []
    taken: set[str] = set()
    groups: dict[tuple[str, str], list[str]] = {}  # 'x.idx' and 'x.sub' move together under one new name
    for folder, name in subs:
        if not kodi_finds(folder, name):
            groups.setdefault((folder, os.path.splitext(name)[0]), []).append(name)
    # Of two in one language the plain one is kept and the one for the hard of hearing set aside.
    for (folder, bare), names in sorted(groups.items(), key=lambda g: _kind(g[0][1])[2]):
        found = owner(folder, names[0])
        paths = [f"{lib}/{folder}/{n}" for n in names]
        if found is None:
            if tv:
                leftovers += [{"path": p, "why": "belongs to no video"} for p in paths]
            continue
        d, stem = found
        lang, forced, sdh = _kind(bare[len(stem):] if bare.lower().startswith(stem.lower()) else bare)
        item = per_video.setdefault(found, {"path": f"{lib}/{d}/{stem}", "move": [], "drop": [], "dirs": []})
        if folder.startswith(d + "/"):
            for k in range(folder.count("/"), d.count("/"), -1):  # the folders between it and the video, emptied by the move
                p = f"{lib}/{'/'.join(folder.split('/')[:k + 1])}"
                if p not in item["dirs"]:
                    item["dirs"].append(p)
        if lang is not None and (lang not in KEEP or (lang, forced) in have.get(found, set())):
            item["drop"] += paths
            continue
        parts = _new_name(stem, lang, forced, sdh)
        new, k = ".".join(parts), 2
        exts = [os.path.splitext(n)[1].lower() for n in names]
        while any(f"{d}/{new}{e}".lower() in taken or os.path.lexists(os.path.join(root, d, new + e)) for e in exts):
            new, k = ".".join([parts[0], str(k), *parts[1:]]), k + 1  # 'x.2.en': the language stays last for Kodi
        for n, e in zip(names, exts, strict=True):
            taken.add(f"{d}/{new}{e}".lower())
            item["move"].append([f"{lib}/{folder}/{n}", f"{lib}/{d}/{new}{e}"])
        if lang:
            have.setdefault(found, set()).add((lang, forced))
    fixes = []
    for (d, stem), item in per_video.items():
        if not item["move"] and not item["drop"]:
            continue
        video = next((n for n in os.listdir(os.path.join(root, d)) if os.path.splitext(n)[0] == stem and is_video(n)), stem)
        m = NUMBERS.search(stem)
        label = f"{unit} S{int(m.group(1)):02d}E{int(m.group(2)):02d}" if tv and m else (unit if not tv else stem)
        parts = [f"{len(item['move'])} to move beside it"] if item["move"] else []
        if item["drop"]:
            parts.append(f"{len(item['drop'])} other language{'s' if len(item['drop']) != 1 else ''} or extra to quarantine")
        item["dirs"].sort(key=lambda p: -p.count("/"))  # deepest first: 'Subs/x' before 'Subs'
        fixes.append({**item, "path": f"{lib}/{d}/{video}", "label": label, "why": ", ".join(parts)})
    return fixes, leftovers
