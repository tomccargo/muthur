"""Renaming an episode in the library to the library's naming ('Show - S01E02 - Title.mkv'), with what belongs
to it (its NFO, thumbnail and subtitles), and Kodi following: the renamed file is a new file to Kodi, so it scans
the folder, the new entry gets the old one's play count and resume point, and the old entry goes.

Renames only happen while Kodi answers: without it the watched status would stay behind on the old entry.
"""
from __future__ import annotations

import os

from .apply import SUBTITLE_EXTS, belongs_to
from .naming import episode_path


def new_name(show_folder: str, file: str, season: int, numbers: list[int], title: str | None) -> str:
    """The file name the library gives this episode, in the show's own folder name: 'The Office (US) - S02E01 - The Dundies.mkv'."""
    return episode_path(show_folder, None, season, numbers, title, os.path.splitext(file)[1]).rsplit("/", 1)[1]


def sidecars(folder: str, stem: str) -> list[str]:
    """The files beside a video that belong to it: 'x.nfo', 'x-thumb.jpg', 'x.tbn', 'x.en.srt'."""
    own = {stem + ".nfo", stem + "-thumb.jpg", stem + "-thumb.png", stem + ".tbn"}
    return [n for n in sorted(os.listdir(folder)) if n in own or (n.lower().endswith(SUBTITLE_EXTS) and belongs_to(n, stem))]


def moves(root: str, rel: str, new: str) -> list[tuple[str, str]]:
    """[(from, to)] under root, the video first. rel: 'Show/Season 1/x.mkv'; new: the video's new file name."""
    folder, name = rel.rsplit("/", 1)
    stem, new_stem = os.path.splitext(name)[0], os.path.splitext(new)[0]
    out = [(rel, f"{folder}/{new}")]
    out += [(f"{folder}/{n}", f"{folder}/{new_stem}{n[len(stem):]}") for n in sidecars(os.path.join(root, *folder.split("/")), stem)]
    return out


def rename(journal, run: int, root: str, lib: str, rel: str, new: str) -> str:
    """Rename the video and what belongs to it, journalled. Returns its new library path ('TV/…'). Nothing moves
    when any target exists already (muthur never overwrites)."""
    todo = moves(root, rel, new)
    if todo[0][0] == todo[0][1]:
        return f"{lib}/{rel}"
    full = lambda p: os.path.join(root, *p.split("/"))  # noqa: E731
    leaving = {a.lower() for a, _ in todo}
    for _, b in todo:
        if os.path.lexists(full(b)) and b.lower() not in leaving:
            raise ValueError(f"{b.rsplit('/', 1)[1]} already exists")
    for a, b in todo:
        journal.move(run, f"{lib}/{rel}", full(a), full(b), "move")
    return f"{lib}/{todo[0][1]}"


def follow_in_kodi(kodi, renamed: list[tuple[str, str]], roots: dict[str, str], before: dict) -> dict:
    """Kodi takes the renamed files: each folder is scanned once, then every new entry gets the old one's play count
    and resume point and the old entry goes. renamed: (old, new) library paths; before: Kodi's items by library path,
    read before the renames (read_before)."""
    from .duplicates import _carry
    from .kodi import folder_name

    prefixes = {lib: kodi.source_prefix(folder_name(root)) for lib, root in roots.items()}
    scanned: set[str] = set()
    followed, problems = 0, []
    for old, new in renamed:
        lib, _, rel = new.partition("/")
        prefix = prefixes.get(lib)
        if prefix:
            folder = prefix + rel.rsplit("/", 1)[0] + "/"
            if folder not in scanned:
                kodi.scan_and_wait(folder)
                scanned.add(folder)
        r = _carry(kodi, {"kind": "episode", "plan": {"final": new}, "copies": [{"path": old}]}, before, prefixes, scan=False)
        if r.get("ok"):
            followed += 1
        else:
            problems.append({"path": new, "why": r.get("why")})
    return {"followed": followed, "problems": problems}


def read_before(kodi, roots: dict[str, str]) -> dict:
    """Kodi's video items by lower-case library path ('tv/show/season 1/x.mkv'), with play count and resume point."""
    from .kodi import folder_name
    from .watched import Watched

    prefixes = {lib: kodi.source_prefix(folder_name(root)) for lib, root in roots.items()}
    out = {}
    for i in Watched.read_kodi(kodi):
        for lib, pre in prefixes.items():
            if pre and (i["file"] or "").lower().startswith(pre.lower()):
                out[f"{lib}/{i['file'][len(pre):]}".lower()] = i
    return out
