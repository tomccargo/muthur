"""Kodi's extra entries: a film or episode Kodi lists more than once while its video is on disk once. One entry is
for a path whose video is gone (a rename or move Kodi never followed), or a second entry for the same file.

Health removes the extra entry after carrying its play count, last played date and resume point to the entry that
stays, so Kodi shows each item once and no watched status is lost. An entry whose video is gone and that has no
other entry stays as it is: it is the only place Kodi shows that item's watched status. Two copies on disk are
Duplicates' business, not this."""
from __future__ import annotations

import os

from .watched import Watched


def _parts(file: str) -> list[str]:
    """A film in parts is one entry: 'stack://a.avi , b.avi'."""
    return [p.strip() for p in file[len("stack://"):].split(" , ")] if file.startswith("stack://") else [file]


def _library_path(file: str, prefixes: dict) -> tuple[str, str] | None:
    """('Film', 'Dune (2021)/Dune (2021).mkv') for a file in one of Kodi's sources for the library; None otherwise."""
    for lib, prefix in prefixes.items():
        if prefix and file.lower().startswith(prefix.lower()):
            return lib, file[len(prefix):]
    return None


class _Disk:
    """Whether a file is there, also without regard to case: Kodi reads the share that way."""

    def __init__(self):
        self.dirs: dict[str, dict[str, str] | None] = {}

    def _names(self, folder: str) -> dict[str, str] | None:
        if folder not in self.dirs:
            try:
                self.dirs[folder] = {n.lower(): n for n in os.listdir(folder)}
            except OSError:
                self.dirs[folder] = None
        return self.dirs[folder]

    def state(self, root: str, rel: str) -> str:
        """'here', 'case' (there only when capitals don't count) or 'gone'."""
        if os.path.isfile(os.path.join(root, *rel.split("/"))):
            return "here"
        cur = root
        for part in rel.split("/"):
            names = self._names(cur)
            if not names or part.lower() not in names:
                return "gone"
            cur = os.path.join(cur, names[part.lower()])
        return "case" if os.path.isfile(cur) else "gone"


def extra(items: list[dict], roots: dict[str, str], prefixes: dict) -> list[dict]:
    """The entries to remove. items: Watched.read_kodi; roots and prefixes per library ('TV', 'Film')."""
    disk, by_key = _Disk(), {}  # type: ignore[var-annotated]
    for i in items:
        found = [_library_path(p, prefixes) for p in _parts(i.get("file") or "")]
        if not found or None in found:
            continue  # not in the library's folders
        states = [disk.state(roots[lib], rel) for lib, rel in found]  # type: ignore[misc]
        state = "here" if "here" in states else "case" if "case" in states else "gone"
        lib, rel = found[0]  # type: ignore[misc]
        by_key.setdefault(i["key"], []).append({**i, "lib": lib, "rel": rel, "state": state})
    out = []
    for group in by_key.values():
        present = [i for i in group if i["state"] != "gone"]
        if len(group) < 2 or not present:
            continue
        stays = max(present, key=lambda i: (i["state"] == "here", i["playcount"], i["resume"], -i["kodiid"]))
        for i in group:
            if i is stays:
                continue
            if i["state"] == "gone":
                why = "its video is gone"
            elif i["rel"].lower() == stays["rel"].lower():
                why = "the same video twice"
            else:
                continue  # another copy on disk
            out.append({"path": f"{i['lib']}/{i['rel']}", "label": i["label"], "kind": i["kind"], "kodiid": i["kodiid"],
                        "stays": stays["kodiid"], "staysPath": f"{stays['lib']}/{stays['rel']}", "why": why})
    return sorted(out, key=lambda x: x["label"].lower())


METHODS = {"movie": ("VideoLibrary.GetMovieDetails", "moviedetails", "movieid", "VideoLibrary.SetMovieDetails", "VideoLibrary.RemoveMovie"),
           "episode": ("VideoLibrary.GetEpisodeDetails", "episodedetails", "episodeid", "VideoLibrary.SetEpisodeDetails",
                       "VideoLibrary.RemoveEpisode")}


def _details(kodi, kind: str, kodiid: int) -> dict | None:
    get, key, id_key, _, _ = METHODS[kind]
    try:
        return (kodi.call(get, {id_key: kodiid, "properties": ["file", "playcount", "lastplayed", "resume"]}) or {}).get(key)
    except RuntimeError:  # Kodi no longer has it
        return None


def remove(kodi, entries: list[dict], backup=None, progress=None) -> dict:
    """Carry each extra entry's watched state to the one that stays, then remove it. backup(items): muthur's watched
    backup, taken first. progress(done): after each entry. Returns {'done', 'failed': [{path, why}]}."""
    if not entries:
        return {"done": 0, "failed": []}
    if not kodi or not kodi.check().get("connected"):
        return {"done": 0, "failed": [{"path": x["path"], "why": "Kodi is off: turn it on and apply again"} for x in entries]}
    if backup:
        backup(Watched.read_kodi(kodi))  # the watched status as it is, before any entry goes
    done, failed = 0, []
    for n, x in enumerate(entries):
        _, _, id_key, setter, remover = METHODS[x["kind"]]
        try:
            old, new = _details(kodi, x["kind"], x["kodiid"]), _details(kodi, x["kind"], x["stays"])
            if old is None:
                done += 1  # already gone
            elif new is None:
                failed.append({"path": x["path"], "why": "Kodi no longer lists the entry that would keep its watched status; check the library again"})
            else:
                params = {id_key: x["stays"]}
                was, now = old.get("resume") or {}, new.get("resume") or {}
                if (old.get("playcount") or 0) > (new.get("playcount") or 0):
                    params.update(playcount=old["playcount"], **({"lastplayed": old["lastplayed"]} if old.get("lastplayed") else {}))
                elif not new.get("playcount") and (was.get("position") or 0) > (now.get("position") or 0):
                    params["resume"] = {"position": was["position"], "total": was.get("total") or 0}
                if len(params) > 1:
                    kodi.call(setter, params)
                kodi.call(remover, {id_key: x["kodiid"]})
                done += 1
        except Exception as e:  # Kodi went away or refused: the entry stays as it was
            failed.append({"path": x["path"], "why": f"Kodi didn't take it: {e}"})
        if progress:
            progress(n + 1)
    return {"done": done, "failed": failed}
