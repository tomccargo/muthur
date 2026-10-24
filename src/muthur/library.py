"""Walk an existing TV or Film library and group files into shows and movies. Read-only."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .parse import EXTRAS_DIR, SAMPLE, is_video

BIG_VIDEO = 400 * 1024 * 1024  # anything smaller next to a movie is an extra, trailer or sample


@dataclass
class FileEntry:
    parts: list[str]  # path relative to the library root, split
    size: int


@dataclass
class ShowDir:
    name: str
    nfo: str | None  # absolute path of tvshow.nfo
    videos: list[FileEntry] = field(default_factory=list)


@dataclass
class MovieUnit:
    key: str  # folder name, or the file stem for a loose file
    folder: bool
    main: FileEntry | None = None
    others: list[FileEntry] = field(default_factory=list)  # extras, samples, second movies
    nfo: str | None = None
    flags: list[str] = field(default_factory=list)


def _walk(root: str):
    """Yield (relative parts, size) for every file under root."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "@", "#"))]
        rel = os.path.relpath(dirpath, root)
        base = [] if rel == "." else rel.split(os.sep)
        for name in filenames:
            try:
                size = os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                size = 0
            yield [*base, name], size


def scan_tv(root: str) -> list[ShowDir]:
    shows: dict[str, ShowDir] = {}
    for entry in sorted(os.listdir(root)):
        if os.path.isdir(os.path.join(root, entry)) and not entry.startswith((".", "@", "#")):
            nfo = os.path.join(root, entry, "tvshow.nfo")
            shows[entry] = ShowDir(entry, nfo if os.path.isfile(nfo) else None)
    for parts, size in _walk(root):
        if len(parts) >= 2 and parts[0] in shows and is_video(parts[-1]):
            shows[parts[0]].videos.append(FileEntry(parts, size))
    return list(shows.values())


def _is_minor(parts: list[str], size: int) -> bool:
    return bool(SAMPLE.search(parts[-1])) or any(EXTRAS_DIR.match(p) or p.lower() == "sample" for p in parts[1:-1]) or size < BIG_VIDEO


def scan_film(root: str) -> list[MovieUnit]:
    units: dict[str, MovieUnit] = {}
    loose_nfos: dict[str, str] = {}
    folder_files: dict[str, list[tuple[list[str], int]]] = {}

    for parts, size in _walk(root):
        name = parts[-1]
        if len(parts) == 1:
            stem, ext = os.path.splitext(name)
            if is_video(name):
                units[stem] = MovieUnit(stem, folder=False, main=FileEntry(parts, size))
            elif ext.lower() == ".nfo":
                loose_nfos[stem] = os.path.join(root, name)
        else:
            folder_files.setdefault(parts[0], []).append((parts, size))

    for stem, nfo in loose_nfos.items():
        if stem in units:
            units[stem].nfo = nfo
        else:
            units[stem] = MovieUnit(stem, folder=False, nfo=nfo, flags=["missing-video"])

    for folder, files in folder_files.items():
        unit = MovieUnit(folder, folder=True)
        videos = [(p, s) for p, s in files if is_video(p[-1])]
        majors = sorted([(p, s) for p, s in videos if not _is_minor(p, s)], key=lambda x: -x[1])
        minors = [(p, s) for p, s in videos if _is_minor(p, s)]
        if majors:
            unit.main = FileEntry(*majors[0])
            unit.others = [FileEntry(p, s) for p, s in majors[1:] + minors]
            if len(majors) > 1:
                unit.flags.append("multiple-main-videos")
        elif minors:
            p, s = max(minors, key=lambda x: x[1])
            unit.main = FileEntry(p, s)
            unit.others = [FileEntry(q, t) for q, t in minors if q is not p]
            unit.flags.append("only-small-videos")
        else:
            unit.flags.append("missing-video")

        nfos = [p for p, _ in files if p[-1].lower().endswith(".nfo") and len(p) == 2]
        if unit.main is not None:
            stem = os.path.splitext(unit.main.parts[-1])[0]
            preferred = [p for p in nfos if p[-1][:-4] == stem] or [p for p in nfos if p[-1].lower() == "movie.nfo"]
            nfos = preferred or nfos
        if nfos:
            unit.nfo = os.path.join(root, *nfos[0])
        units[f"{folder}/"] = unit
    return sorted(units.values(), key=lambda u: u.key.lower())


def save(obj, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(o) for o in obj], f, ensure_ascii=False)


def load_tv(path: str) -> list[ShowDir]:
    with open(path, encoding="utf-8") as f:
        return [ShowDir(d["name"], d["nfo"], [FileEntry(**v) for v in d["videos"]]) for d in json.load(f)]


def load_film(path: str) -> list[MovieUnit]:
    def fe(v):
        return FileEntry(**v) if v else None
    with open(path, encoding="utf-8") as f:
        return [MovieUnit(d["key"], d["folder"], fe(d["main"]), [fe(o) for o in d["others"]], d["nfo"], d["flags"]) for d in json.load(f)]
