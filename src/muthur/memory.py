"""Fill the ID memory from the existing TV library. Read-only on the library.

A show is only remembered when muthur's own match agrees with the IDs in its
tvshow.nfo: the first dry run found NFOs that describe a different show, and
remembering those would repeat the mistake for every new episode.

Running it again is safe: entries are refreshed in place, and entries learned
from the library that no longer hold are dropped, but only after a complete
run over a non-empty TV folder. Choices confirmed in Review are never dropped.
"""
from __future__ import annotations

from . import library
from .dryrun import run_show
from .parse import parse_show_folder
from .store import Store


def import_tv(tmdb, tv_root: str, store: Store, job=None) -> dict:
    shows = library.scan_tv(tv_root)
    if job:
        job.total = len(shows)
    counts = {"shows": len(shows), "remembered": 0, "disagree": 0, "unverified": 0, "forgotten": 0}
    kept: set = set()
    for show in shows:
        if job:
            job.done += 1
        row, _ = run_show(tmdb, show, parse=store.parsed)
        if row.verdict != "agree" or not row.best_ids.get("tmdb"):
            counts["disagree" if row.verdict.startswith("disagree") else "unverified"] += 1
            continue
        folder = parse_show_folder(show.name)
        tmdb_id = int(row.best_ids["tmdb"])
        for name in {folder.title, row.best_title}:
            kept.add(store.remember("tv", name, tmdb_id, row.best_year, row.best_title, show.name, "library"))
        counts["remembered"] += 1
    if shows:  # an empty or unreachable TV folder must not wipe the memory
        counts["forgotten"] = store.forget_library_except("tv", kept)
    return counts
