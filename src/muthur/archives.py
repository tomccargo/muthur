"""Downloads that arrive packed: look inside first, unpack only real media, and never a fake.

A fake archive is a common trick: a zip or rar named like an episode or a film that holds a program, asks for a password
(to be bought from a "password site"), or holds no video at all. None of it runs on the NAS, but it clutters the downloads.
An archive is unpacked only when its list of contents holds a video and nothing else gives it away:

    fake     a program inside, a password, a path that leaves its folder, a link, or no video at all: it goes to quarantine
    media    a video inside and nothing suspicious: unpacked next to where it came, the archive itself to quarantine
    unknown  muthur can't tell or can't do it (in parts, an archive inside an archive, not enough room, unreadable):
             it stays where it is, for the reader

Zip is read with Python's own zipfile; rar, 7z and tar with bsdtar (libarchive, which reads RAR and RAR 5 but not a
set split over several volumes). Both refuse to write outside the folder they unpack into, and muthur checks the names
first anyway. What was unpacked is checked again on disk before it joins the download.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field

from .parse import SAMPLE, is_video

# Programs, as the Inbox knows them (inbox.EXECUTABLE); kept here so this module stands alone.
EXECUTABLE = re.compile(r"(?i)\.(exe|scr|com|pif|bat|cmd|vbs|vbe|js|jse|wsf|msi|ps1|lnk|hta|jar|apk|dll|sh|elf|bin)$")
ARCHIVE_NAME = re.compile(r"(?i)\.(zip|rar|7z|tar|tgz|tar\.gz|tar\.xz|r\d\d|z\d\d|part\d+\.rar|7z\.\d{3}|zip\.\d{3})$")
# The later volumes of a split set: '.r00', '.part02.rar', '.z01', '.7z.002', '.zip.002'.
LATER_VOLUME = re.compile(r"(?i)\.(r\d\d|z\d\d|part0*(?:[2-9]|\d{2,})\.rar|(?:7z|zip)\.(?!0*1$)\d{3})$")
FIRST_OF_SET = re.compile(r"(?i)\.(part0*1\.rar|(?:7z|zip)\.0*1)$")
ROOM = 512 * 1024 * 1024  # what must stay free on the disk after unpacking
LARGEST = 200 * 1024 ** 3  # more than this unpacked is not a download, whatever it says
STAGING = ".muthur-unpacking"  # inside the downloads folder (same disk: the unpacked files are renamed into place)
TOOL = "bsdtar"
TIMEOUT = 3 * 3600


def is_archive(name: str) -> bool:
    return bool(ARCHIVE_NAME.search(name))


@dataclass
class Look:
    verdict: str  # 'media' | 'fake' | 'unknown'
    why: str  # a sentence for the reader
    archives: list[str] = field(default_factory=list)  # the archives to unpack (first volumes), relative to the download
    size: int = 0  # bytes once unpacked, as far as the archive says


def _bad_name(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return name.startswith(("/", "\\")) or bool(re.match(r"^[A-Za-z]:", name)) or ".." in parts


def _members_zip(path: str) -> tuple[list[tuple[str, int]], str | None]:
    """(name, size) of each file in a zip, or the reason it can't be trusted."""
    out: list[tuple[str, int]] = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.flag_bits & 0x1:
                return out, "It asks for a password, a known trick to sell one."
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                return out, "It holds a link to somewhere else on the disk."
            if not info.is_dir():
                out.append((info.filename, info.file_size))
    return out, None


_LISTED = re.compile(r"^(\S{10})\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\d+\s+[\d:]+\s+(.*)$")


def _members_tool(path: str, run=subprocess.run) -> tuple[list[tuple[str, int]], str | None]:
    """bsdtar -tv lists like ls -l: mode, links, owner, group, size, month, day, time or year, name."""
    try:
        r = run([TOOL, "-tvf", path], capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        raise ValueError("muthur has no program here that opens this kind of archive.")
    except subprocess.SubprocessError:
        raise ValueError("Reading the archive took too long.")
    if r.returncode:
        if re.search(r"(?i)encrypt|passphrase|password", r.stderr or ""):
            return [], "It asks for a password, a known trick to sell one."
        raise ValueError("muthur couldn't read the archive.")
    out: list[tuple[str, int]] = []
    for line in (r.stdout or "").splitlines():
        m = _LISTED.match(line)
        if not m:
            continue
        mode, size, name = m.group(1), int(m.group(2)), m.group(3)
        if mode.startswith("l") or mode.startswith("h"):
            return out, "It holds a link to somewhere else on the disk."
        if not mode.startswith("d"):
            out.append((name.split(" -> ")[0], size))
    return out, None


def members(path: str, run=subprocess.run) -> tuple[list[tuple[str, int]], str | None]:
    if path.lower().endswith(".zip"):
        try:
            return _members_zip(path)
        except (zipfile.BadZipFile, OSError, ValueError):
            raise ValueError("muthur couldn't read the zip file.")
    return _members_tool(path, run)


def _judge(listed: list[tuple[str, int]]) -> tuple[str, str]:
    names = [n for n, _ in listed]
    if any(_bad_name(n) for n in names):
        return "fake", "It tries to write outside its own folder."
    programs = [n for n in names if EXECUTABLE.search(n)]
    if programs:
        return "fake", f"It holds a program ({os.path.basename(programs[0])}), not a video."
    videos = [n for n in names if is_video(os.path.basename(n)) and not n.lower().endswith(".iso")]
    if any(not SAMPLE.search(os.path.basename(n)) for n in videos):
        return "media", ""
    if any(is_archive(n) for n in names):
        return "unknown", "An archive inside an archive. Unpack it yourself."
    if videos:
        return "fake", "It holds only a sample clip."
    return "fake", "It holds no video."


def look(base: str, entry: str, run=subprocess.run) -> Look:
    """What the archives in this download hold. entry: the download, relative to base (the downloads folder)."""
    path = os.path.join(base, *entry.split("/"))
    if os.path.isfile(path):
        files = [entry.rsplit("/", 1)[-1]]
        root = os.path.dirname(path)
    else:
        root = path
        files = sorted(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/")
                       for dp, _, names in os.walk(path) for n in names)
    packed = [f for f in files if is_archive(f)]
    if not packed:
        return Look("unknown", "No archive in it.")
    if any(LATER_VOLUME.search(f) for f in packed) or any(FIRST_OF_SET.search(f) for f in packed):
        return Look("unknown", "Packed in several parts, which muthur can't join. Unpack it yourself.")
    total, why = 0, None
    for a in packed:
        try:
            listed, problem = members(os.path.join(root, *a.split("/")), run)
        except ValueError as e:
            return Look("unknown", str(e))
        if problem:
            return Look("fake", problem, packed)
        verdict, why = _judge(listed)
        if verdict != "media":
            return Look(verdict, why, packed)
        total += sum(s for _, s in listed)
    if total > LARGEST:
        return Look("unknown", "It says it unpacks to more than 200 GB. muthur leaves that to you.", packed)
    if shutil.disk_usage(base).free < total + ROOM:
        return Look("unknown", "Not enough free room on the disk to unpack it.", packed, total)
    return Look("media", "", packed, total)


def _extract_zip(path: str, dest: str) -> None:
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = os.path.normpath(os.path.join(dest, *info.filename.replace("\\", "/").split("/")))
            if os.path.commonpath([dest, target]) != os.path.normpath(dest):
                raise ValueError("It tries to write outside its own folder.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "xb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)


def _extract_tool(path: str, dest: str, run=subprocess.run) -> None:
    # bsdtar refuses absolute names and '..' unless told otherwise (-P), and never follows links out of dest.
    try:
        r = run([TOOL, "-xf", path, "-C", dest, "--no-same-owner", "--no-same-permissions"], capture_output=True, text=True,
                timeout=TIMEOUT)
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        raise ValueError(f"Unpacking didn't work ({type(e).__name__}).")
    if r.returncode:
        if re.search(r"(?i)encrypt|passphrase|password", r.stderr or ""):
            raise PermissionError("It asks for a password, a known trick to sell one.")
        raise ValueError("Unpacking stopped halfway; the archive may be damaged.")


def _check_unpacked(dest: str) -> str | None:
    """What gives an unpacked folder away on disk, after the fact: a link, a program, or no video."""
    videos = 0
    for dp, dirs, names in os.walk(dest):
        for n in dirs + names:
            if os.path.islink(os.path.join(dp, n)):
                return "It holds a link to somewhere else on the disk."
        for n in names:
            if EXECUTABLE.search(n):
                return f"It holds a program ({n}), not a video."
            if is_video(n) and not SAMPLE.search(n):
                videos += 1
    return None if videos else "It holds no video."


def unpack(base: str, entry: str, found: Look, run=subprocess.run) -> dict:
    """Unpack a download judged 'media'. The files land in the download's own folder (a loose archive gets a folder named
    after it), never over an existing file; their times are the archive's, so the download stays as settled as it was.
    Returns {folder, files, archives}: the download's folder relative to base, how many files came out, and the archive
    files (relative to base) that are now spent. Raises ValueError (or PermissionError for a password) and leaves the
    download exactly as it was."""
    path = os.path.join(base, *entry.split("/"))
    loose = os.path.isfile(path)
    folder_rel = (entry.rsplit(".", 1)[0] if loose else entry).rstrip(". ")
    if loose and re.search(r"(?i)\.tar$", folder_rel):
        folder_rel = folder_rel[:-4]
    folder = os.path.join(base, *folder_rel.split("/"))
    if loose and os.path.lexists(folder):
        raise ValueError("A folder by the archive's name is already there.")
    root = os.path.dirname(path) if loose else path
    stage = os.path.join(base, STAGING, uuid.uuid4().hex[:12])
    os.makedirs(stage)
    try:
        when = max(os.stat(os.path.join(root, *a.split("/"))).st_mtime for a in found.archives)
        for a in found.archives:
            src = os.path.join(root, *a.split("/"))
            sub = os.path.join(stage, os.path.dirname(a)) if os.path.dirname(a) else stage
            os.makedirs(sub, exist_ok=True)
            if a.lower().endswith(".zip"):
                _extract_zip(src, sub)
            else:
                _extract_tool(src, sub, run)
        problem = _check_unpacked(stage)
        if problem:
            raise PermissionError(problem)
        moves = []
        for dp, _, names in os.walk(stage):
            for n in names:
                rel = os.path.relpath(os.path.join(dp, n), stage)
                target = os.path.join(folder, rel)
                if os.path.lexists(target):
                    raise ValueError(f"{rel.replace(os.sep, '/')} is already in the download; muthur never overwrites.")
                moves.append((os.path.join(dp, n), target))
        for src, target in moves:
            os.utime(src, (when, when))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(src, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        try:
            os.rmdir(os.path.join(base, STAGING))
        except OSError:
            pass
    return {"folder": folder_rel, "files": len(moves), "archives": [entry] if loose else [f"{entry}/{a}" for a in found.archives]}
