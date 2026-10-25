"""Match parsed names to TMDB entries, with scores and an auto/review decision.

The rule that matters most: never guess silently. A match is only "auto" when
it is clearly better than every alternative; everything else goes to review.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .text import best_similarity, normalize, strip_article

AUTO_SCORE = 0.90
AUTO_MARGIN = 0.15
MAX_CANDIDATES = 6
EPISODE_GATE = 0.90  # share of the files' SxxEyy that must exist on TMDB; single misses are flagged per episode
ALT_TITLE_CAP = 0.85  # a match on an alternative title is weaker evidence than on the main or original title
POPULARITY_WEIGHT = 0.08
EXACT_TITLE = 0.95  # below this the title was matched fuzzily (typo, extra words): a human confirms
RIVAL_TITLE = 0.97  # a runner-up only competes with an exact match when its own title is (nearly) the same

SHOW_WEIGHTS = {"title": 0.45, "year": 0.20, "episodes": 0.25, "country": 0.10}
MOVIE_WEIGHTS = {"title": 0.50, "year": 0.30, "runtime": 0.20}


@dataclass
class Candidate:
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    signals: dict[str, float | None] = field(default_factory=dict)
    score: float = 0.0
    imdb_id: str | None = None
    tvdb_id: str | None = None
    language: str | None = None  # original language (ISO 639-1)
    titles: list[str] = field(default_factory=list)


@dataclass
class Match:
    status: str  # "auto" | "review" | "none"
    best: Candidate | None = None
    candidates: list[Candidate] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def _year_signal(want: int | None, have: int | None) -> float | None:
    if want is None:
        return None
    if have is None:
        return 0.3
    # One year off is common: festival premiere vs release, or a December pilot.
    return {0: 1.0, 1: 0.8}.get(abs(want - have), 0.0)


def _title_signal(query: str, main: list[str], alternative: list[str]) -> float:
    return max(best_similarity(query, main), min(ALT_TITLE_CAP, best_similarity(query, alternative)))


def _combine(signals: dict, weights: dict) -> float:
    used = {k: w for k, w in weights.items() if signals.get(k) is not None}
    total = sum(used.values())
    return sum(signals[k] * w for k, w in used.items()) / total if total else 0.0


def _finish(cands: list[Candidate], weights: dict, popularity: dict[int, float]) -> None:
    """Final score: the weighted signals plus a small share for popularity relative to the other candidates."""
    top = max((math.log10(1 + p) for p in popularity.values()), default=0) or 1
    for c in cands:
        c.signals["popularity"] = math.log10(1 + popularity.get(c.tmdb_id, 0)) / top
        c.score = round((1 - POPULARITY_WEIGHT) * _combine(c.signals, weights) + POPULARITY_WEIGHT * c.signals["popularity"], 4)


def _alt_titles(details: dict, key: str) -> list[str]:
    alt = details.get("alternative_titles") or {}
    return [a.get("title") for a in alt.get(key, []) if a.get("title")]


def _same_title(a: Candidate, b: Candidate) -> bool:
    na, nb = strip_article(normalize(a.title)), strip_article(normalize(b.title))
    return na == nb or strip_article(normalize(a.original_title)) == strip_article(normalize(b.original_title))


def _decide(cands: list[Candidate], gate: str | None) -> Match:
    """gate: a signal that must be perfect for auto (episodes for shows)."""
    cands.sort(key=lambda c: c.score, reverse=True)
    if not cands:
        return Match("none", reasons=["no candidates on TMDB"])
    best = cands[0]
    m = Match("auto", best, cands)
    if best.score < AUTO_SCORE:
        m.reasons.append(f"best score {best.score:.2f} < {AUTO_SCORE}")
    if best.signals.get("title", 0) < EXACT_TITLE:
        m.reasons.append(f"title not an exact match ({best.signals['title']:.2f})")
    exact = best.signals.get("title", 0) >= EXACT_TITLE
    rivals = [c for c in cands[1:] if not exact or c.signals.get("title", 0) >= RIVAL_TITLE]
    if rivals and best.score - rivals[0].score < AUTO_MARGIN:
        m.reasons.append(f"runner-up too close ({rivals[0].title} {rivals[0].year}: {rivals[0].score:.2f})")
    if gate and best.signals.get(gate) is not None and best.signals[gate] < EPISODE_GATE:
        m.reasons.append(f"{gate} missing on the best match ({best.signals[gate]:.2f})")
    if best.signals.get("year") is None:
        # A title shared by another plausible entry, with nothing to tell them apart, always needs a human.
        for other in cands[1:]:
            if _same_title(best, other) and (gate is None or (other.signals.get(gate) or 0) >= EPISODE_GATE):
                m.reasons.append(f"title clash without a year: {other.title} ({other.year})")
                break
    if m.reasons:
        m.status = "review"
    return m


def _search(search, title: str, year: int | None) -> list[dict]:
    """Search with the year first, then without. If both find nothing (typos such as
    'Abbot Elementary'), retry with one word left out at a time and keep close titles."""
    results = search(title, year) if year else []
    if not any(best_similarity(title, [r.get("name") or r.get("title") or "", r.get("original_name") or r.get("original_title") or ""]) >= EXACT_TITLE
               for r in results):
        # The year filter can hide the right entry (premiere vs release year), so look without it too.
        known = {r["id"] for r in results}
        extra = [*(search(title, year - 1) if year else []), *(search(title, year + 1) if year else []), *search(title, None)]
        for r in extra:
            if r["id"] not in known:
                known.add(r["id"])
                results.append(r)
    words = title.split()
    if not results and len(words) > 1:
        seen = {}
        for i in range(len(words)):
            for r in search(" ".join(words[:i] + words[i + 1:]), None)[:10]:
                name = r.get("name") or r.get("title") or ""
                orig = r.get("original_name") or r.get("original_title") or ""
                if best_similarity(title, [name, orig]) >= 0.8:
                    seen.setdefault(r["id"], r)
        results = list(seen.values())
    return results


def identify_show(source, title: str, year: int | None = None, country: str | None = None,
                  episodes: set[tuple[int, int]] | None = None, absolute_max: int | None = None) -> Match:
    """source: an object with search_tv(query, year) and tv(id) (see Tmdb)."""
    results = _search(source.search_tv, title, year)
    cands, popularity = [], {}
    regular = {(s, e) for s, e in (episodes or set()) if s and s > 0}
    for r in results[:MAX_CANDIDATES]:
        d = source.tv(r["id"]) or r
        seasons = {s["season_number"]: s.get("episode_count") or 0 for s in d.get("seasons", [])}
        c = Candidate(r["id"], d.get("name") or r.get("name", ""), d.get("original_name") or r.get("original_name", ""),
                      _year(d.get("first_air_date") or r.get("first_air_date")))
        ext = d.get("external_ids") or {}
        c.imdb_id, c.tvdb_id = ext.get("imdb_id"), (str(ext["tvdb_id"]) if ext.get("tvdb_id") else None)
        c.language = d.get("original_language") or r.get("original_language")
        alternative = _alt_titles(d, "results")
        c.titles = [c.title, c.original_title, *alternative]
        c.signals["title"] = _title_signal(title, [c.title, c.original_title], alternative)
        c.signals["year"] = _year_signal(year, c.year)
        if regular and seasons:
            c.signals["episodes"] = sum(1 for s, e in regular if e <= seasons.get(s, 0)) / len(regular)
        elif absolute_max and seasons:
            total = sum(n for s, n in seasons.items() if s > 0)
            c.signals["episodes"] = 1.0 if absolute_max <= total else total / absolute_max
        else:
            c.signals["episodes"] = None
        origin = d.get("origin_country") or r.get("origin_country") or []
        c.signals["country"] = (1.0 if country in origin else 0.0) if country else None
        popularity[c.tmdb_id] = r.get("popularity") or 0
        cands.append(c)
    _finish(cands, SHOW_WEIGHTS, popularity)
    return _decide(cands, gate="episodes")


def identify_movie(source, title: str | list[str], year: int | None = None, duration_s: int | None = None) -> Match:
    """source: an object with search_movie(query, year) and movie(id) (see Tmdb).
    title: one query, or several (the first preferred) when a name can be read more than one way."""
    queries = [title] if isinstance(title, str) else [t for t in title if t]
    results, seen = [], set()
    for q in queries:
        found = _search(source.search_movie, q, year)
        results += [r for r in found[:MAX_CANDIDATES] if r["id"] not in seen]
        seen.update(r["id"] for r in found)
        if any(best_similarity(q, [r.get("title", ""), r.get("original_title", "")]) >= EXACT_TITLE for r in found):
            break
    cands, popularity = [], {}
    for i, r in enumerate(results[:MAX_CANDIDATES * len(queries)]):
        c = Candidate(r["id"], r.get("title", ""), r.get("original_title", ""), _year(r.get("release_date")))
        c.language = r.get("original_language")
        main = [c.title, c.original_title]
        alternative, runtime = [], None
        if i < 3 or max(best_similarity(q, main) for q in queries) >= 0.9:
            d = source.movie(r["id"]) or {}
            alternative = _alt_titles(d, "titles")
            runtime = d.get("runtime")
            c.imdb_id = d.get("imdb_id") or (d.get("external_ids") or {}).get("imdb_id")
        c.titles = main + alternative
        c.signals["title"] = max(_title_signal(q, main, alternative) for q in queries)
        c.signals["year"] = _year_signal(year, c.year)
        if duration_s and runtime:
            off = abs(duration_s / 60 - runtime) / runtime
            c.signals["runtime"] = max(0.0, 1 - max(0.0, off - 0.08) / 0.22)
        elif duration_s:
            c.signals["runtime"] = 0.4  # TMDB has no runtime: usually an obscure duplicate entry
        else:
            c.signals["runtime"] = None
        popularity[c.tmdb_id] = r.get("popularity") or 0
        cands.append(c)
    _finish(cands, MOVIE_WEIGHTS, popularity)
    return _decide(cands, gate=None)
