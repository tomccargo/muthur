"""Milestone 1: read-only dry run against an existing library.

Every show and movie is treated as if it had just been downloaded: muthur sees
only folder and file names (plus the file duration), never the NFO. Its match
is then compared with the IDs already in the library's NFO files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from . import library
from .identify import Match, identify_movie, identify_show
from .nfo import read_nfo
from .parse import parse_episode, parse_movie, parse_show_folder

ID_TYPES = ("tmdb", "tvdb", "imdb")


@dataclass
class Row:
    kind: str  # "show" | "movie"
    name: str
    query: str
    query_year: int | None
    status: str  # auto | review | none | skipped
    verdict: str  # see verdict()
    best: str = ""
    best_ids: dict = field(default_factory=dict)
    truth_ids: dict = field(default_factory=dict)
    truth_title: str | None = None
    reasons: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    episodes: int = 0
    blocked_episodes: int = 0
    flags: list[str] = field(default_factory=list)


def _ids(c) -> dict:
    ids = {"tmdb": str(c.tmdb_id)}
    if c.imdb_id:
        ids["imdb"] = c.imdb_id
    if c.tvdb_id:
        ids["tvdb"] = c.tvdb_id
    return ids


def verdict(truth: dict, match: Match) -> str:
    truth = {k: v for k, v in truth.items() if k in ID_TYPES}
    if not truth:
        return "no-truth"
    if match.best is None:
        return "no-match"

    def same(c):
        ids = _ids(c)
        return any(ids.get(k) == v for k, v in truth.items())

    def comparable(c):
        return bool(_ids(c).keys() & truth.keys())

    if same(match.best):
        return "agree"
    if not comparable(match.best):
        return "unknown"
    if any(same(c) for c in match.candidates[1:]):
        return "disagree-truth-in-candidates"
    return "disagree"


def _cached_scan(kind: str, root: str, cache_dir: str, rescan: bool):
    key = hashlib.sha1(os.path.abspath(root).lower().encode()).hexdigest()[:10]
    path = os.path.join(cache_dir, f"scan-{kind}-{key}.json")
    if not rescan and os.path.isfile(path):
        return (library.load_tv if kind == "tv" else library.load_film)(path)
    t = time.time()
    data = library.scan_tv(root) if kind == "tv" else library.scan_film(root)
    library.save(data, path)
    print(f"  scanned {kind} in {time.time() - t:.0f}s")
    return data


def run_show(tmdb, show: library.ShowDir) -> tuple[Row, list]:
    folder = parse_show_folder(show.name)
    eps = [parse_episode(v.parts) for v in show.videos]
    usable = [e for e in eps if not e.blocked and not e.sample and not e.extra]
    sample = {(e.season, n) for e in usable if e.season for n in e.episodes}
    absolute = max((e.absolute for e in usable if e.absolute), default=None)
    truth = read_nfo(show.nfo) if show.nfo else None

    row = Row("show", show.name, folder.title or show.name, folder.year, "skipped", "no-truth",
              episodes=len(eps), blocked_episodes=sum(e.blocked for e in eps))
    if truth:
        row.truth_ids, row.truth_title = {k: v for k, v in truth.ids.items() if k in ID_TYPES}, truth.title
    if not show.videos:
        row.flags.append("no-videos")
        return row, eps
    m = identify_show(tmdb, folder.title or show.name, folder.year, folder.country, sample, absolute)
    _fill(row, m)
    return row, eps


def probe_duration(path: str | None) -> int | None:
    """Duration in seconds from the file header via ffprobe (reads only the start of the file)."""
    if not path or not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return int(float(out)) if out else None
    except (subprocess.SubprocessError, ValueError):
        return None


def run_movie(tmdb, unit: library.MovieUnit, film_root: str | None = None) -> Row:
    row = Row("movie", unit.key, "", None, "skipped", "no-truth", flags=list(unit.flags))
    truth = read_nfo(unit.nfo) if unit.nfo else None
    if truth:
        row.truth_ids, row.truth_title = {k: v for k, v in truth.ids.items() if k in ID_TYPES}, truth.title
    if unit.main is None:
        return row
    p = parse_movie(unit.main.parts)
    row.query, row.query_year = p.title or unit.key, p.year
    row.flags += p.flags
    duration = truth.duration_s if truth else None
    if not duration and film_root:
        duration = probe_duration(os.path.join(film_root, *unit.main.parts))
    m = identify_movie(tmdb, [row.query, *p.alt_titles], p.year, duration)
    _fill(row, m)
    return row


def _fill(row: Row, m: Match) -> None:
    row.status = m.status
    row.reasons = m.reasons
    row.verdict = verdict(row.truth_ids, m)
    if m.best:
        row.best = f"{m.best.title} ({m.best.year})"
        row.best_ids = _ids(m.best)
    row.candidates = [f"{c.title} ({c.year}) {c.score:.2f} " + " ".join(f"{k}={v:.2f}" for k, v in c.signals.items() if v is not None)
                      for c in m.candidates[:4]]


def run(tmdb, tv_root: str | None, film_root: str | None, out_dir: str, cache_dir: str,
        rescan: bool = False, limit: int | None = None, workers: int = 8) -> str:
    stamp = time.strftime("%Y%m%d-%H%M")
    out = os.path.join(out_dir, f"dryrun-{stamp}")
    os.makedirs(out, exist_ok=True)
    rows: list[Row] = []
    episode_rows = []

    if tv_root:
        print("TV: scanning", tv_root)
        shows = _cached_scan("tv", tv_root, cache_dir, rescan)[:limit]
        print(f"TV: identifying {len(shows)} shows")
        with ThreadPoolExecutor(workers) as pool:
            for row, eps in pool.map(lambda s: run_show(tmdb, s), shows):
                rows.append(row)
                episode_rows += [(row.name, e) for e in eps]

    if film_root:
        print("Film: scanning", film_root)
        units = _cached_scan("film", film_root, cache_dir, rescan)[:limit]
        print(f"Film: identifying {len(units)} movies")
        with ThreadPoolExecutor(workers) as pool:
            rows += list(pool.map(lambda u: run_movie(tmdb, u, film_root), units))

    _write(out, rows, episode_rows)
    print(f"TMDB: {tmdb.calls} calls, {tmdb.hits} from cache")
    return out


def _outcome(r: Row) -> str:
    if r.status == "skipped":
        return "skipped"
    if r.verdict in ("no-truth", "unknown"):
        return f"{r.status}, no ground truth"
    if r.status == "auto":
        return "auto, correct" if r.verdict == "agree" else "AUTO, DISAGREES WITH NFO"
    if r.status == "review":
        return {"agree": "review, right one ranked first",
                "disagree-truth-in-candidates": "review, right one among candidates"}.get(r.verdict, "review, right one not offered")
    return "no match"


ORDER = ["AUTO, DISAGREES WITH NFO", "auto, correct", "review, right one ranked first", "review, right one among candidates",
         "review, right one not offered", "no match", "auto, no ground truth", "review, no ground truth",
         "none, no ground truth", "skipped"]


def _write(out: str, rows: list[Row], episode_rows: list) -> None:
    with open(os.path.join(out, "details.json"), "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=1)

    with open(os.path.join(out, "matches.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "folder", "outcome", "query", "year", "best", "best_ids", "nfo_ids", "nfo_title", "reasons", "flags"])
        for r in rows:
            w.writerow([r.kind, r.name, _outcome(r), r.query, r.query_year or "", r.best, json.dumps(r.best_ids),
                        json.dumps(r.truth_ids), r.truth_title or "", " | ".join(r.reasons), " ".join(r.flags)])

    flagged = [(show, e) for show, e in episode_rows if e.flags and e.flags != ["absolute-number"] or e.blocked]
    with open(os.path.join(out, "episodes-flagged.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["show", "file", "season", "episodes", "absolute", "flags"])
        for show, e in flagged:
            w.writerow([show, e.path, e.season if e.season is not None else "", " ".join(map(str, e.episodes)),
                        e.absolute or "", " ".join(e.flags)])

    lines = ["# muthur dry run", "", f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Read-only: nothing in the library was changed.", ""]
    for kind, label in (("show", "TV shows"), ("movie", "Movies")):
        sub = [r for r in rows if r.kind == kind]
        if not sub:
            continue
        counts = Counter(_outcome(r) for r in sub)
        lines += [f"## {label}: {len(sub)}", "", "| Outcome | Count |", "|---|---|"]
        lines += [f"| {o} | {counts[o]} |" for o in ORDER if counts.get(o)]
        judged = sum(v for k, v in counts.items() if "ground truth" not in k and k != "skipped")
        if judged:
            auto_ok = counts["auto, correct"]
            lines += ["", f"Of {judged} with known IDs: {auto_ok} correct automatic matches ({auto_ok / judged:.0%}), "
                          f"**{counts['AUTO, DISAGREES WITH NFO']} automatic matches that disagree with the NFO**, "
                          f"{judged - auto_ok - counts['AUTO, DISAGREES WITH NFO']} sent to review or unmatched.", ""]
        for o in ("AUTO, DISAGREES WITH NFO", "review, right one not offered", "no match"):
            items = [r for r in sub if _outcome(r) == o]
            if items:
                lines += [f"### {o} ({len(items)})", ""]
                for r in items:
                    lines.append(f"- **{r.name}** → muthur: {r.best or '—'} {json.dumps(r.best_ids)} · NFO: {r.truth_title} {json.dumps(r.truth_ids)}"
                                 + (f" · {'; '.join(r.reasons)}" if r.reasons else ""))
                lines.append("")
        reasons = Counter(reason.split(" (")[0].split(":")[0] for r in sub if r.status == "review" for reason in r.reasons)
        if reasons:
            lines += ["### Why items went to review", "", "| Reason | Count |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in reasons.most_common()]
            lines.append("")

    if episode_rows:
        total = len(episode_rows)
        blocked = sum(e.blocked for _, e in episode_rows)
        flags = Counter(f for _, e in episode_rows for f in e.flags)
        lines += ["## Episode file names", "", f"{total} episode files, {total - blocked} usable ({(total - blocked) / total:.1%}), {blocked} need attention.", "",
                  "| Flag | Files |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in flags.most_common()]
        lines += ["", "Details: `episodes-flagged.csv`. All matches: `matches.csv`.", ""]

    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
