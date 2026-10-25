"""Notes on what went into quarantine and why (ARCHITECTURE.md §9).

Each day folder in the quarantine holds one 'muthur-notes.jsonl': a line per item with where it
came from, where it is now, the run that moved it, and a sentence on why. The folder can then be
understood without muthur, and the Quarantine panel shows the reasons.
"""
from __future__ import annotations

import json
import os
import time

NOTES = "muthur-notes.jsonl"


def note(quarantine: str, dst: str, src: str, run: int, why: str) -> None:
    """Record one quarantined item. dst is its path inside the quarantine."""
    rel = os.path.relpath(dst, quarantine).split(os.sep)
    if len(rel) < 2:
        return
    line = {"at": time.time(), "run": run, "from": src, "to": "/".join(rel[1:]), "why": why}
    with open(os.path.join(quarantine, rel[0], NOTES), "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def notes(quarantine: str, day: str) -> list[dict]:
    path = os.path.join(quarantine, day, NOTES)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out
