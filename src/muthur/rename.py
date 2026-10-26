"""Renaming a video in the library to the library's naming ('Show - S01E02 - Title.mkv', 'Title (Year)/Title (Year).mkv'),
with what belongs to it (its NFO, artwork named after it and subtitles), and Kodi following: the renamed file is a new
file to Kodi, so it scans the folder, the new entry gets the old one's play count and resume point, and the old entry goes.

Renames only happen while Kodi answers: without it the watched status would stay behind on the old entry.
"""
from __future__ import annotations

import os

from .apply import SUBTITLE_EXTS, belongs_to
from .naming import episode_path

MANY_FOLDERS = 3  # above this many renamed folders in one source, Kodi scans the source once instead
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


def follow_in_kodi(kodi, renamed: list[tuple[str, str]], roots: dict[str, str], before: dict, done=None) -> dict:
    """Kodi takes the renamed files: each folder is scanned once, then every new entry gets the old one's play count
    and resume point and the old entry goes. renamed: (old, new) library paths ('TV/…' an episode, 'Film/…' a film);
    before: Kodi's items by library path, read before the renames (read_before). done(old) after each one Kodi took
    or answered about; when Kodi goes away the rest is left for later ('kodiAway')."""
    import requests

    from .duplicates import _carry
    from .kodi import folder_name

    prefixes = {lib: kodi.source_prefix(folder_name(root)) for lib, root in roots.items()}

    def folder_of(new: str) -> str | None:
        lib, _, rel = new.partition("/")
        prefix = prefixes.get(lib)
        return prefix + (rel.rsplit("/", 1)[0] + "/" if "/" in rel else "") if prefix else None

    # Many folders in one source: one scan of the whole source. Kodi skips every folder whose modification time
    # didn't change, so it only reads the renamed ones, without waiting on each folder in turn.
    per_source: dict[str, set[str]] = {}
    for _, new in renamed:
        if (f := folder_of(new)) is not None:
            per_source.setdefault(prefixes[new.partition("/")[0]] or "", set()).add(f)
    whole = {src for src, folders in per_source.items() if len(folders) > MANY_FOLDERS}
    scanned: set[str] = set()
    followed, problems = 0, []  # type: ignore[var-annotated]
    for n, (old, new) in enumerate(renamed):
        folder = folder_of(new)
        source = prefixes.get(new.partition("/")[0])
        try:
            if folder and source in whole and source not in scanned:
                kodi.scan_and_wait(source, limit=3600)
                scanned.add(source)
            elif folder and source not in whole and folder not in scanned:
                kodi.scan_and_wait(folder)
                scanned.add(folder)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return {"followed": followed, "problems": problems, "kodiAway": len(renamed) - n}
        g = {"kind": "episode" if new.startswith("TV/") else "movie", "plan": {"final": new}, "copies": [{"path": old}]}
        r = _carry(kodi, g, before, prefixes, scan=False)
        if not r.get("ok") and not kodi.check().get("connected"):
            return {"followed": followed, "problems": problems, "kodiAway": len(renamed) - n}
        if r.get("ok"):
            followed += 1
        else:
            problems.append({"path": new, "why": r.get("why")})
        if done:
            done(old)
    return {"followed": followed, "problems": problems}


# Renames whose Kodi step hasn't happened yet survive a restart: muthur finishes them when it starts again or
# when Kodi answers again (web.py). Kodi keeps the old entry, with its watched status, until then.
PENDING = "kodi.pendingRenames"


def remember(store, renamed: list[tuple[str, str]]) -> None:
    have = [tuple(p) for p in store.get(PENDING) or []]
    store.put(PENDING, [list(p) for p in dict.fromkeys(have + [tuple(p) for p in renamed])])


def forget(store, old: str) -> None:
    store.put(PENDING, [p for p in store.get(PENDING) or [] if p[0] != old])


def pending(store) -> list[tuple[str, str]]:
    return [tuple(p) for p in store.get(PENDING) or []]  # type: ignore[misc]


def from_run(ops: list[dict], roots: dict[str, str]) -> list[tuple[str, str]]:
    """(old, new) library paths of the videos a run renamed, from its journal: for a run a restart cut short. A film
    whose folder moved after its video was renamed ends up in that folder."""
    from .parse import is_video

    def lib_path(full: str) -> str | None:
        for lib, root in roots.items():
            base = os.path.normpath(root)
            if os.path.normpath(full).startswith(base + os.sep):
                return f"{lib}/{os.path.relpath(full, base).replace(os.sep, '/')}"
        return None

    out = []
    moves = [o for o in ops if o["op"] == "move" and o["status"] == "done"]
    for o in moves:
        if not is_video(o["src"] or "") or not is_video(o["dst"]):
            continue
        dst = o["dst"]
        for later in moves:  # its folder moved afterwards
            if later["id"] > o["id"] and later["item"] == o["item"] and later["src"] == os.path.dirname(dst):
                dst = os.path.join(later["dst"], os.path.basename(dst))
        new = lib_path(dst)
        if new and o["item"] != new:
            out.append((o["item"], new))
    return out


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
