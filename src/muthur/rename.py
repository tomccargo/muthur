"""Renaming a video in the library to the library's naming ('Show - S01E02 - Title.mkv', 'Title (Year)/Title (Year).mkv'),
with what belongs to it (its NFO, artwork named after it and subtitles), and Kodi following: the renamed file is a new
file to Kodi, so it scans the folder, the new entry gets the old one's play count and resume point, and the old entry goes.

Renames only happen while Kodi answers: without it the watched status would stay behind on the old entry.
"""
from __future__ import annotations

import os

from .apply import SUBTITLE_EXTS, belongs_to
from .naming import episode_path

ART_TYPES = ("thumb", "poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "disc", "logo", "characterart", "keyart")


def new_name(show_folder: str, file: str, season: int, numbers: list[int], title: str | None) -> str:
    """The file name the library gives this episode, in the show's own folder name: 'The Office (US) - S02E01 - The Dundies.mkv'."""
    return episode_path(show_folder, None, season, numbers, title, os.path.splitext(file)[1]).rsplit("/", 1)[1]


def sidecars(folder: str, stem: str) -> list[str]:
    """The files beside a video that belong to it: 'x.nfo', 'x.tbn', 'x-thumb.jpg', 'x-poster.jpg', 'x.en.srt'."""
    own = {stem + ".nfo", stem + ".tbn"} | {f"{stem}-{t}{e}" for t in ART_TYPES for e in (".jpg", ".png")}
    return [n for n in sorted(os.listdir(folder)) if n in own or (n.lower().endswith(SUBTITLE_EXTS) and belongs_to(n, stem))]


def _split(rel: str) -> tuple[str, str]:
    return tuple(rel.rsplit("/", 1)) if "/" in rel else ("", rel)  # type: ignore[return-value]


def _join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def moves(root: str, rel: str, new_rel: str) -> list[tuple[str, str]]:
    """[(from, to)] under root, the video first. rel: 'Show/Season 1/x.mkv'; new_rel: where the video goes, in the
    same folder or another ('Film (1999)/Film (1999).mkv' for a loose film)."""
    folder, name = _split(rel)
    new_folder, new = _split(new_rel)
    stem, new_stem = os.path.splitext(name)[0], os.path.splitext(new)[0]
    out = [(rel, new_rel)]
    out += [(_join(folder, n), _join(new_folder, new_stem + n[len(stem):])) for n in sidecars(os.path.join(root, *folder.split("/")), stem)]
    return out


def rename(journal, run: int, root: str, lib: str, rel: str, new_rel: str) -> str:
    """Rename the video and what belongs to it, journalled. Returns its new library path ('TV/…'). Nothing moves
    when any target exists already (muthur never overwrites)."""
    todo = moves(root, rel, new_rel)
    if todo[0][0] == todo[0][1]:
        return f"{lib}/{rel}"
    full = lambda p: os.path.join(root, *p.split("/"))  # noqa: E731
    leaving = {a.lower() for a, _ in todo}
    for _, b in todo:
        if os.path.lexists(full(b)) and b.lower() not in leaving:
            raise ValueError(f"{b.rsplit('/', 1)[-1]} already exists")
    for a, b in todo:
        journal.move(run, f"{lib}/{rel}", full(a), full(b), "move")
    return f"{lib}/{todo[0][1]}"


def follow_in_kodi(kodi, renamed: list[tuple[str, str]], roots: dict[str, str], before: dict) -> dict:
    """Kodi takes the renamed files: each folder is scanned once, then every new entry gets the old one's play count
    and resume point and the old entry goes. renamed: (old, new) library paths ('TV/…' an episode, 'Film/…' a film);
    before: Kodi's items by library path, read before the renames (read_before)."""
    from .duplicates import _carry
    from .kodi import folder_name

    prefixes = {lib: kodi.source_prefix(folder_name(root)) for lib, root in roots.items()}
    scanned: set[str] = set()
    followed, problems = 0, []
    for old, new in renamed:
        lib, _, rel = new.partition("/")
        prefix = prefixes.get(lib)
        if prefix:
            folder = prefix + (rel.rsplit("/", 1)[0] + "/" if "/" in rel else "")
            if folder not in scanned:
                kodi.scan_and_wait(folder)
                scanned.add(folder)
        g = {"kind": "episode" if lib == "TV" else "movie", "plan": {"final": new}, "copies": [{"path": old}]}
        r = _carry(kodi, g, before, prefixes, scan=False)
        if r.get("ok"):
            followed += 1
        else:
            problems.append({"path": new, "why": r.get("why")})
    return {"followed": followed, "problems": problems}


def read_before(kodi, roots: dict[str, str], backup=None) -> dict:
    """Kodi's video items by lower-case library path ('tv/show/season 1/x.mkv'), with play count and resume point.
    backup(items): muthur's watched backup taken from the same read, so it is current at the moment of a rename."""
    from .kodi import folder_name
    from .watched import Watched

    prefixes = {lib: kodi.source_prefix(folder_name(root)) for lib, root in roots.items()}
    items = Watched.read_kodi(kodi)
    if backup:
        backup(items)
    out = {}
    for i in items:
        for lib, pre in prefixes.items():
            if pre and (i["file"] or "").lower().startswith(pre.lower()):
                out[f"{lib}/{i['file'][len(pre):]}".lower()] = i
    return out
